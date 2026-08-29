"""
tDEB Simulator API
==================
CRUD for transport networks, batch and streaming simulation, the template
catalogue, and per-user equation editing.

Every model belongs to the authenticated user.  Solving is CPU-bound, so both
the batch endpoint and each streaming step run in a worker thread rather than on
the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.core.auth import get_current_user, verify_token
from app.core.database import get_database
from app.tdeb.core import (
    EDITABLE_SECTIONS, Edge, EdgeParams, EnvironmentParams, EquationSet,
    DEFAULT_METHOD, KNOWN_VARS, Node, NodeParams, NodeType, SOLVER_METHODS,
    SimulationParams,
    Solver, StreamingRun, TransportNetwork, TransportType,
    build_template, list_templates, validate_formula,
)
from app.tdeb.service import (
    TDebEquationService, TDebModelNotFound, TDebModelService, TDebModelTooLarge,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Pacing for WebSocket streaming, in seconds between snapshots. Slow enough that
# the browser can animate each step, fast enough that a year-long run finishes.
STREAM_INTERVAL = 0.02


# ─── Request models ───────────────────────────────────────────────────

class NetworkCreate(BaseModel):
    """Create from a template id, an imported network document, or empty."""
    template: Optional[str] = None
    network: Optional[Dict[str, Any]] = None
    name: Optional[str] = None


class NetworkUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class NodeCreate(BaseModel):
    name: str = Field(default="New Node", max_length=120)
    node_type: str = "custom"
    x: float = 300
    y: float = 300
    initial_value: float = 0.0
    color: str = Field(default="#4A90D9", max_length=32)
    params: Dict[str, float] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    node_type: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    value: Optional[float] = None
    initial_value: Optional[float] = None
    color: Optional[str] = Field(default=None, max_length=32)
    params: Optional[Dict[str, float]] = None


class EdgeCreate(BaseModel):
    source_id: str
    target_id: str
    name: str = Field(default="transport", max_length=120)
    transport_type: str = "linear"
    params: Dict[str, Any] = Field(default_factory=dict)


class EdgeUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)
    transport_type: Optional[str] = None
    params: Optional[Dict[str, Any]] = None


class SimRequest(BaseModel):
    t_end: float = 365.0
    dt_output: float = 1.0
    method: str = DEFAULT_METHOD
    temperature: float = 293.15     # Kelvin
    food_density: float = 1.0


class FormulaCheck(BaseModel):
    formula: str = Field(max_length=2000)


class EquationUpdate(BaseModel):
    """Update one equation entry, e.g. section='transport', key='linear'."""
    section: str
    key: Optional[str] = None
    data: Dict[str, Any] = Field(default_factory=dict)


# ─── Helpers ──────────────────────────────────────────────────────────

def _model_service() -> TDebModelService:
    return TDebModelService()


def _equation_service() -> TDebEquationService:
    return TDebEquationService()


async def _load(user_id: str, model_id: str) -> TransportNetwork:
    try:
        return await _model_service().load(user_id, model_id)
    except TDebModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")


async def _save(user_id: str, model_id: str, network: TransportNetwork) -> dict:
    try:
        return await _model_service().save(user_id, model_id, network)
    except TDebModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    except TDebModelTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc))


def _as_response(model_id: str, network_dict: dict) -> dict:
    """
    Serialize a network for the API, keyed by its stored model id.

    ``TransportNetwork`` carries its own short id, left over from when networks
    lived in a process dict. The persisted Mongo id is what every other endpoint
    addresses, so it has to win — spreading the network last would silently
    shadow it and make follow-up requests 404.
    """
    return {**network_dict, "id": model_id}


def _parse_node_type(value: str) -> NodeType:
    try:
        return NodeType(value)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown node type '{value}'. Expected one of: "
            f"{', '.join(t.value for t in NodeType)}",
        )


def _parse_transport_type(value: str) -> TransportType:
    try:
        return TransportType(value)
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown transport type '{value}'. Expected one of: "
            f"{', '.join(t.value for t in TransportType)}",
        )


def _apply_node_params(params: NodeParams, incoming: Dict[str, float]) -> None:
    """Copy recognised numeric parameters onto ``params``, ignoring the rest."""
    for key, value in incoming.items():
        if key in NodeParams.__dataclass_fields__:
            setattr(params, key, float(value))


def _apply_edge_params(params: EdgeParams, incoming: Dict[str, Any]) -> None:
    for key, value in incoming.items():
        if key not in EdgeParams.__dataclass_fields__:
            continue
        if key == "custom_formula":
            setattr(params, key, str(value)[:2000])
        else:
            try:
                setattr(params, key, float(value))
            except (TypeError, ValueError):
                continue


# ─── Templates ────────────────────────────────────────────────────────

@router.get("/templates")
async def get_templates(current_user: dict = Depends(get_current_user)) -> List[dict]:
    """The built-in model templates and organism presets."""
    return list_templates()


# ─── Network CRUD ─────────────────────────────────────────────────────

@router.get("/models")
async def list_models(current_user: dict = Depends(get_current_user)) -> List[dict]:
    """Summaries of every model owned by the caller."""
    return await _model_service().list_models(current_user["id"])


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def create_model(payload: NetworkCreate,
                       current_user: dict = Depends(get_current_user)) -> dict:
    """Create a model from a template, an imported document, or from scratch."""
    template_id = None

    if payload.template:
        network = build_template(payload.template)
        if network is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Unknown template '{payload.template}'"
            )
        template_id = payload.template
    elif payload.network is not None:
        try:
            network = TransportNetwork.from_dict(payload.network)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Could not read the imported model: {exc}",
            )
        if payload.name:
            network.name = payload.name
    else:
        network = TransportNetwork(name=payload.name or "New model")

    try:
        created = await _model_service().create(current_user["id"], network, template_id)
    except TDebModelTooLarge as exc:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, str(exc))

    return _as_response(created["id"], created["network"])


@router.get("/models/{model_id}")
async def get_model(model_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)
    return _as_response(model_id, network.to_dict())


@router.put("/models/{model_id}")
async def rename_model(model_id: str, payload: NetworkUpdate,
                       current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)
    network.name = payload.name.strip()
    saved = await _save(current_user["id"], model_id, network)
    return _as_response(model_id, saved)


@router.delete("/models/{model_id}")
async def delete_model(model_id: str, current_user: dict = Depends(get_current_user)) -> dict:
    try:
        await _model_service().delete(current_user["id"], model_id)
    except TDebModelNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Model not found")
    return {"deleted": True}


@router.get("/models/{model_id}/export")
async def export_model(model_id: str,
                       current_user: dict = Depends(get_current_user)) -> dict:
    """The full network document, suitable for saving to a .json file."""
    network = await _load(current_user["id"], model_id)
    return network.to_dict()


# ─── Node CRUD ────────────────────────────────────────────────────────

@router.post("/models/{model_id}/nodes", status_code=status.HTTP_201_CREATED)
async def add_node(model_id: str, payload: NodeCreate,
                   current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)

    params = NodeParams()
    _apply_node_params(params, payload.params)

    node = Node(
        name=payload.name,
        node_type=_parse_node_type(payload.node_type),
        value=payload.initial_value,
        initial_value=payload.initial_value,
        x=payload.x, y=payload.y,
        color=payload.color,
        params=params,
    )
    network.add_node(node)
    await _save(current_user["id"], model_id, network)
    return node.to_dict()


@router.put("/models/{model_id}/nodes/{node_id}")
async def update_node(model_id: str, node_id: str, payload: NodeUpdate,
                      current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)
    node = network.nodes.get(node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")

    if payload.name is not None:
        node.name = payload.name
    if payload.node_type is not None:
        node.node_type = _parse_node_type(payload.node_type)
        network._rebuild_state_order()
    if payload.x is not None:
        node.x = payload.x
    if payload.y is not None:
        node.y = payload.y
    if payload.initial_value is not None:
        node.initial_value = payload.initial_value
    if payload.value is not None:
        node.value = payload.value
    if payload.color is not None:
        node.color = payload.color
    if payload.params:
        _apply_node_params(node.params, payload.params)

    await _save(current_user["id"], model_id, network)
    return node.to_dict()


@router.delete("/models/{model_id}/nodes/{node_id}")
async def delete_node(model_id: str, node_id: str,
                      current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)
    if node_id not in network.nodes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Node not found")
    network.remove_node(node_id)
    await _save(current_user["id"], model_id, network)
    return {"deleted": True}


# ─── Edge CRUD ────────────────────────────────────────────────────────

@router.post("/models/{model_id}/edges", status_code=status.HTTP_201_CREATED)
async def add_edge(model_id: str, payload: EdgeCreate,
                   current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)

    params = EdgeParams()
    _apply_edge_params(params, payload.params)

    edge = Edge(
        source_id=payload.source_id,
        target_id=payload.target_id,
        name=payload.name,
        transport_type=_parse_transport_type(payload.transport_type),
        params=params,
    )
    try:
        network.add_edge(edge)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    await _save(current_user["id"], model_id, network)
    return edge.to_dict()


@router.put("/models/{model_id}/edges/{edge_id}")
async def update_edge(model_id: str, edge_id: str, payload: EdgeUpdate,
                      current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)
    edge = network.edges.get(edge_id)
    if edge is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Edge not found")

    if payload.name is not None:
        edge.name = payload.name
    if payload.transport_type is not None:
        edge.transport_type = _parse_transport_type(payload.transport_type)
    if payload.params:
        _apply_edge_params(edge.params, payload.params)

    await _save(current_user["id"], model_id, network)

    # A custom formula that does not evaluate is saved anyway — the user is
    # mid-edit — but reported so the inspector can show the error inline.
    result = edge.to_dict()
    if edge.transport_type == TransportType.CUSTOM and edge.params.custom_formula:
        is_valid, error = Edge.validate_formula(edge.params.custom_formula)
        if not is_valid:
            result["formula_error"] = error
    return result


@router.delete("/models/{model_id}/edges/{edge_id}")
async def delete_edge(model_id: str, edge_id: str,
                      current_user: dict = Depends(get_current_user)) -> dict:
    network = await _load(current_user["id"], model_id)
    if edge_id not in network.edges:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Edge not found")
    network.remove_edge(edge_id)
    await _save(current_user["id"], model_id, network)
    return {"deleted": True}


# ─── Simulation ───────────────────────────────────────────────────────

@router.post("/models/{model_id}/simulate")
async def simulate(model_id: str, payload: SimRequest,
                   current_user: dict = Depends(get_current_user)) -> dict:
    """Solve the full horizon and return every state and flux time series."""
    network = await _load(current_user["id"], model_id)
    equations = await _equation_service().build_equation_set(current_user["id"])

    if payload.method not in SOLVER_METHODS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Unknown solver method '{payload.method}'. "
            f"Expected one of: {', '.join(SOLVER_METHODS)}",
        )

    env = EnvironmentParams(
        temperature=payload.temperature,
        food_density=payload.food_density,
    )
    sim_params = SimulationParams(
        t_end=payload.t_end,
        dt_output=payload.dt_output,
        method=payload.method,
    )
    try:
        sim_params.validate()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    solver = Solver(network, equations, sim_params)
    # solve_ivp is CPU-bound; keep it off the event loop.
    result = await run_in_threadpool(solver.run, env)
    return result.to_dict()


# ─── WebSocket streaming ──────────────────────────────────────────────

async def _ws_user(token: Optional[str]) -> Optional[dict]:
    """Resolve the JWT passed as a query param on the WebSocket upgrade."""
    if not token:
        return None
    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None
        user_doc = await get_database().users.find_one({"_id": ObjectId(user_id)})
        if not user_doc:
            return None
        return {"id": str(user_doc["_id"]), "email": user_doc.get("email", "")}
    except Exception:  # noqa: BLE001 — any failure means "not authenticated"
        return None


@router.websocket("/ws/simulate/{model_id}")
async def stream_simulation(websocket: WebSocket, model_id: str,
                            token: Optional[str] = Query(default=None)):
    """
    Stream a simulation snapshot per output interval.

    The client sends ``{temperature, food_density, t_end, dt_output, method}``
    after the connection opens, then receives ``{time, progress, nodes, flows}``
    messages followed by ``{done: true}``.
    """
    user = await _ws_user(token)
    if not user:
        await websocket.close(code=4401)
        return

    await websocket.accept()

    try:
        network = await _model_service().load(user["id"], model_id)
    except TDebModelNotFound:
        await websocket.send_json({"error": "Model not found"})
        await websocket.close()
        return

    try:
        config = await websocket.receive_json()

        env = EnvironmentParams(
            temperature=float(config.get("temperature", 293.15)),
            food_density=float(config.get("food_density", 1.0)),
        )
        sim_params = SimulationParams(
            t_end=float(config.get("t_end", 365.0)),
            dt_output=float(config.get("dt_output", 1.0)),
            method=str(config.get("method", DEFAULT_METHOD)),
        )

        equations = await _equation_service().build_equation_set(user["id"])
        run = StreamingRun(network, equations, sim_params, env)

        while True:
            # Each step integrates one interval — run it off the event loop so
            # one streaming client cannot stall every other request.
            snapshot = await run_in_threadpool(run.step)
            if snapshot is None:
                break
            await websocket.send_json(snapshot)
            if "error" in snapshot:
                break
            await asyncio.sleep(STREAM_INTERVAL)

        await websocket.send_json({"done": True})

    except WebSocketDisconnect:
        pass
    except ValueError as exc:
        # Invalid solver configuration — report it as a normal stream error.
        try:
            await websocket.send_json({"error": str(exc)})
        except Exception:  # noqa: BLE001 — client already gone
            pass
    except Exception as exc:  # noqa: BLE001
        logger.exception("tDEB stream failed for model %s", model_id)
        try:
            await websocket.send_json({"error": f"Simulation failed: {exc}"})
        except Exception:  # noqa: BLE001
            pass


# ─── Equations ────────────────────────────────────────────────────────

@router.get("/equations")
async def get_equations(current_user: dict = Depends(get_current_user)) -> dict:
    """The caller's active equations — shipped defaults plus their overrides."""
    return await _equation_service().get_resolved(current_user["id"])


@router.get("/equations/defaults")
async def get_default_equations(current_user: dict = Depends(get_current_user)) -> dict:
    """The read-only shipped defaults."""
    from app.tdeb.core import load_defaults
    return load_defaults()


@router.put("/equations")
async def update_equation(payload: EquationUpdate,
                          current_user: dict = Depends(get_current_user)) -> dict:
    """
    Update a single equation entry and return the caller's full resolved set.

    Only formulas (and the non-negativity toggle) are writable; ``ode_rule`` is
    structural and implemented in the solver, so it is not editable.
    """
    if payload.section not in EDITABLE_SECTIONS:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Section '{payload.section}' is not editable. Expected one of: "
            f"{', '.join(EDITABLE_SECTIONS)}",
        )

    service = _equation_service()
    resolved = await service.get_resolved(current_user["id"])

    formula = payload.data.get("formula")
    if formula is not None:
        if not isinstance(formula, str):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Formula must be a string")
        is_valid, error = validate_formula(formula)
        if not is_valid:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid formula: {error}")

    if payload.section == "transport":
        if not payload.key or payload.key not in resolved.get("transport", {}):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Unknown transport kinetics '{payload.key}'",
            )
        if formula is not None:
            resolved["transport"][payload.key]["formula"] = formula
    else:
        target = resolved.setdefault(payload.section, {})
        if formula is not None:
            target["formula"] = formula
        if payload.section == "non_negativity" and "enabled" in payload.data:
            target["enabled"] = bool(payload.data["enabled"])

    return await service.save_resolved(current_user["id"], resolved)


@router.post("/equations/reset")
async def reset_equations(current_user: dict = Depends(get_current_user)) -> dict:
    """Discard the caller's overrides and return to the shipped defaults."""
    return await _equation_service().reset(current_user["id"])


@router.post("/equations/validate")
async def check_formula(payload: FormulaCheck,
                        current_user: dict = Depends(get_current_user)) -> dict:
    """Evaluate a formula against dummy values to check it compiles."""
    is_valid, error = validate_formula(payload.formula)
    return {"valid": is_valid, "error": error, "variables": KNOWN_VARS}
