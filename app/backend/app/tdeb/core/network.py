"""
tDEB Transport Network
======================
A directed graph whose nodes are compartments and whose edges are transport
channels.  The ODE system is generated from the topology rather than written
out by hand::

    dX_i/dt = Σ(incoming fluxes) - Σ(outgoing fluxes) - maintenance_i
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from .equations import EquationSet
from .nodes import (
    Node, NodeType, NodeParams,
    create_food_node, create_reserve_node, create_structure_node,
    create_maturity_node, create_reproduction_node, create_gonad_node,
)
from .transport import Edge, EdgeParams, TransportType


@dataclass
class EnvironmentParams:
    """Environmental conditions."""
    temperature: float = 293.15     # Temperature [K] (20°C)
    food_density: float = 1.0       # Functional response f ∈ [0,1]
    toxicant_conc: float = 0.0      # External toxicant [mg/L]

    def to_dict(self) -> dict:
        return {
            "temperature": self.temperature,
            "food_density": self.food_density,
            "toxicant_conc": self.toxicant_conc,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "EnvironmentParams":
        known = {k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__}
        return cls(**known)


class TransportNetwork:
    """
    A DEB transport network representing an organism's energy budget.

    Nodes are compartments, edges are transport channels, and the ODE system is
    assembled automatically from how they are wired together.
    """

    def __init__(self, name: str = "Untitled Model"):
        self.id: str = str(uuid.uuid4())[:8]
        self.name: str = name
        self.nodes: Dict[str, Node] = {}
        self.edges: Dict[str, Edge] = {}
        self.environment: EnvironmentParams = EnvironmentParams()

        # Adjacency indices for fast lookup
        self._incoming: Dict[str, List[str]] = {}  # node_id -> [edge_ids]
        self._outgoing: Dict[str, List[str]] = {}  # node_id -> [edge_ids]

        # Node ordering for the ODE system (excludes FOOD nodes)
        self._state_node_ids: List[str] = []

    # ── topology ──────────────────────────────────────────────────────

    def add_node(self, node: Node) -> Node:
        """Add a node to the network."""
        self.nodes[node.id] = node
        self._incoming.setdefault(node.id, [])
        self._outgoing.setdefault(node.id, [])
        self._rebuild_state_order()
        return node

    def remove_node(self, node_id: str):
        """Remove a node along with every edge touching it."""
        for eid in [
            eid for eid, e in self.edges.items()
            if e.source_id == node_id or e.target_id == node_id
        ]:
            self.remove_edge(eid)

        self.nodes.pop(node_id, None)
        self._incoming.pop(node_id, None)
        self._outgoing.pop(node_id, None)
        self._rebuild_state_order()

    def add_edge(self, edge: Edge) -> Edge:
        """Add a transport edge between two existing nodes."""
        if edge.source_id not in self.nodes:
            raise ValueError(f"Source node {edge.source_id} is not in the network")
        if edge.target_id not in self.nodes:
            raise ValueError(f"Target node {edge.target_id} is not in the network")

        self.edges[edge.id] = edge
        self._outgoing[edge.source_id].append(edge.id)
        self._incoming[edge.target_id].append(edge.id)
        return edge

    def remove_edge(self, edge_id: str):
        """Remove an edge from the network."""
        edge = self.edges.pop(edge_id, None)
        if edge is None:
            return
        if edge_id in self._outgoing.get(edge.source_id, []):
            self._outgoing[edge.source_id].remove(edge_id)
        if edge_id in self._incoming.get(edge.target_id, []):
            self._incoming[edge.target_id].remove(edge_id)

    def _rebuild_state_order(self):
        """Rebuild the state-variable ordering (food sources are not states)."""
        self._state_node_ids = [
            nid for nid, n in self.nodes.items()
            if n.node_type != NodeType.FOOD
        ]

    # ── state vector ──────────────────────────────────────────────────

    def get_state_vector(self) -> np.ndarray:
        return np.array([self.nodes[nid].value for nid in self._state_node_ids])

    def get_initial_state(self) -> np.ndarray:
        return np.array([self.nodes[nid].initial_value for nid in self._state_node_ids])

    def set_state_vector(self, y: np.ndarray):
        for i, nid in enumerate(self._state_node_ids):
            self.nodes[nid].value = float(y[i])

    def get_state_labels(self) -> List[str]:
        return [self.nodes[nid].name for nid in self._state_node_ids]

    def apply_environment(self, env: Optional[EnvironmentParams] = None):
        """
        Adopt ``env`` and push its food density onto the FOOD compartments.

        Food nodes are not state variables, so nothing else would ever update
        them — without this the functional response ``f`` chosen for a run would
        be ignored and every simulation would use whatever the template baked in.
        """
        if env is not None:
            self.environment = env
        for node in self.nodes.values():
            if node.node_type == NodeType.FOOD:
                node.value = self.environment.food_density
                node.initial_value = self.environment.food_density

    # ── ODE system ────────────────────────────────────────────────────

    def derivatives(self, t: float, y: np.ndarray, equations: EquationSet,
                    env: Optional[EnvironmentParams] = None) -> np.ndarray:
        """
        Right-hand side of the ODE system: dX/dt for every state compartment.

        For each state node i::

            dX_i/dt = Σ_j(J_j→i) - Σ_k(J_i→k) - maintenance_i
        """
        if env is None:
            env = self.environment

        self.set_state_vector(y)

        dydt = np.zeros(len(self._state_node_ids))
        idx_map = {nid: i for i, nid in enumerate(self._state_node_ids)}

        for edge in self.edges.values():
            source = self.nodes.get(edge.source_id)
            target = self.nodes.get(edge.target_id)
            if source is None or target is None:
                continue

            flux = edge.compute_flux(
                equations,
                source_value=source.value,
                target_value=target.value,
                temperature=env.temperature,
            )

            if edge.source_id in idx_map:
                dydt[idx_map[edge.source_id]] -= flux
            if edge.target_id in idx_map:
                dydt[idx_map[edge.target_id]] += flux

        # Somatic maintenance is drawn from structure only.
        for i, nid in enumerate(self._state_node_ids):
            node = self.nodes[nid]
            if node.node_type == NodeType.STRUCTURE:
                dydt[i] -= node.maintenance_cost(equations, env.temperature)

        # Keep states from going negative through numerical undershoot.
        if equations.non_negativity_enabled():
            for i in range(len(dydt)):
                if y[i] <= 0 and dydt[i] < 0:
                    dydt[i] = 0.0

        return dydt

    def compute_fluxes(self, equations: EquationSet) -> Dict[str, float]:
        """Current flux on every edge, keyed by edge id (for visualization)."""
        fluxes = {}
        for eid, edge in self.edges.items():
            source = self.nodes.get(edge.source_id)
            target = self.nodes.get(edge.target_id)
            if source is None or target is None:
                fluxes[eid] = 0.0
                continue
            fluxes[eid] = edge.compute_flux(
                equations,
                source_value=source.value,
                target_value=target.value,
                temperature=self.environment.temperature,
            )
        return fluxes

    # ── serialization ─────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": {eid: e.to_dict() for eid, e in self.edges.items()},
            "environment": self.environment.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TransportNetwork":
        """
        Rebuild a network from a serialized dict.

        Edges whose endpoints are missing are dropped rather than raising, so a
        hand-edited or truncated import file still loads.
        """
        net = cls(name=d.get("name") or "Untitled")
        net.id = d.get("id") or net.id

        for nd in (d.get("nodes") or {}).values():
            node = Node.from_dict(nd)
            net.nodes[node.id] = node
            net._incoming[node.id] = []
            net._outgoing[node.id] = []

        net._rebuild_state_order()

        for ed in (d.get("edges") or {}).values():
            try:
                edge = Edge.from_dict(ed)
            except (KeyError, ValueError):
                continue
            if edge.source_id not in net.nodes or edge.target_id not in net.nodes:
                continue
            net.edges[edge.id] = edge
            net._outgoing[edge.source_id].append(edge.id)
            net._incoming[edge.target_id].append(edge.id)

        if d.get("environment"):
            net.environment = EnvironmentParams.from_dict(d["environment"])

        return net

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_json(cls, s: str) -> "TransportNetwork":
        return cls.from_dict(json.loads(s))


# ─── Predefined network templates ────────────────────────────────────

def create_standard_kdeb() -> TransportNetwork:
    """
    Standard kDEB model expressed as a transport network — the reference case.

    Food → [assimilation] → Reserve → [κ-split] → Structure
                                    → [(1-κ) split] → Maturity → Reproduction
    """
    net = TransportNetwork(name="Standard kDEB")

    food = create_food_node(f=1.0, x=80, y=250)
    reserve = create_reserve_node(E0=50.0, x=300, y=250)
    structure = create_structure_node(V0=0.001, p_M=18.0, E_G=2800.0, x=500, y=150)
    maturity = create_maturity_node(EH0=0.0, x=500, y=350)
    reproduction = create_reproduction_node(ER0=0.0, x=700, y=350)

    for node in (food, reserve, structure, maturity, reproduction):
        net.add_node(node)

    net.add_edge(Edge(
        source_id=food.id, target_id=reserve.id,
        name="Assimilation (p_Am)",
        transport_type=TransportType.MICHAELIS_MENTEN,
        params=EdgeParams(V_max=100.0, K_m=0.5, efficiency=0.8),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=structure.id,
        name="Somatic (κ·p_C)",
        transport_type=TransportType.KAPPA_SPLIT,
        params=EdgeParams(rate_constant=0.3, kappa=0.8, efficiency=0.8),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=maturity.id,
        name="Development ((1-κ)·p_C)",
        transport_type=TransportType.KAPPA_SPLIT,
        params=EdgeParams(rate_constant=0.3, kappa=0.2, efficiency=0.8),
    ))
    net.add_edge(Edge(
        source_id=maturity.id, target_id=reproduction.id,
        name="Reproduction allocation",
        transport_type=TransportType.THRESHOLD,
        params=EdgeParams(rate_constant=0.5, threshold=10.0, efficiency=0.95),
    ))

    return net


def create_tdeb_with_reproduction() -> TransportNetwork:
    """
    tDEB model with an explicit transport network for reproduction.

    The key departure from kDEB: no fixed κ-rule.  Transport between
    compartments is governed by local kinetics and regulatory signals instead.
    """
    net = TransportNetwork(name="tDEB with Reproduction Module")

    food = create_food_node(f=1.0, x=80, y=250)
    reserve = create_reserve_node(E0=50.0, x=280, y=250)
    structure = create_structure_node(V0=0.001, p_M=18.0, E_G=2800.0, x=480, y=120)
    maturity = create_maturity_node(EH0=0.0, x=480, y=380)
    reproduction = create_reproduction_node(ER0=0.0, x=680, y=250)
    gonad = create_gonad_node(x=680, y=400)

    for node in (food, reserve, structure, maturity, reproduction, gonad):
        net.add_node(node)

    net.add_edge(Edge(
        source_id=food.id, target_id=reserve.id,
        name="Assimilation",
        transport_type=TransportType.MICHAELIS_MENTEN,
        params=EdgeParams(V_max=100.0, K_m=0.5, efficiency=0.8),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=structure.id,
        name="Somatic growth",
        transport_type=TransportType.GRADIENT,
        params=EdgeParams(rate_constant=0.25, efficiency=0.8),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=maturity.id,
        name="Maturation",
        transport_type=TransportType.REGULATED,
        params=EdgeParams(V_max=30.0, K_m=10.0, signal_strength=0.8),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=reproduction.id,
        name="Reproductive allocation",
        transport_type=TransportType.GRADIENT,
        params=EdgeParams(rate_constant=0.15, efficiency=0.9),
    ))
    net.add_edge(Edge(
        source_id=reproduction.id, target_id=gonad.id,
        name="Gamete production",
        transport_type=TransportType.THRESHOLD,
        params=EdgeParams(rate_constant=0.8, threshold=15.0, efficiency=0.95),
    ))

    return net


# ─── Organism examples with real AmP parameters ─────────────────────

def _create_organism_kdeb(
    name: str,
    p_Am: float,
    v: float,
    kappa: float,
    p_M: float,
    E_G: float,
    T_A: float,
    E_Hb: float,
    E_Hp: float,
    kap_X: float = 0.8,
    kap_R: float = 0.95,
    E0: float = 10.0,
    V0: float = 0.001,
) -> TransportNetwork:
    """
    Build a standard kDEB network for a specific organism.

    Parameters come from the Add-my-Pet (AmP) database at T_ref = 293.15 K.
    """
    net = TransportNetwork(name=name)

    food = create_food_node(f=1.0, x=80, y=250)
    reserve = create_reserve_node(E0=E0, x=300, y=250)
    structure = create_structure_node(V0=V0, p_M=p_M, E_G=E_G, x=500, y=150)
    maturity = create_maturity_node(EH0=0.0, x=500, y=350)
    reproduction = create_reproduction_node(ER0=0.0, x=700, y=350)

    for node in (food, reserve, structure, maturity, reproduction):
        node.params.T_A = T_A
        net.add_node(node)

    def ep(**kwargs) -> EdgeParams:
        return EdgeParams(T_A=T_A, **kwargs)

    net.add_edge(Edge(
        source_id=food.id, target_id=reserve.id,
        name="Assimilation (p_Am)",
        transport_type=TransportType.MICHAELIS_MENTEN,
        params=ep(V_max=p_Am, K_m=0.5, efficiency=kap_X),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=structure.id,
        name="Somatic growth (κ·p_C)",
        transport_type=TransportType.KAPPA_SPLIT,
        params=ep(rate_constant=v, kappa=kappa, efficiency=kap_X),
    ))
    net.add_edge(Edge(
        source_id=reserve.id, target_id=maturity.id,
        name="Development ((1-κ)·p_C)",
        transport_type=TransportType.KAPPA_SPLIT,
        params=ep(rate_constant=v, kappa=1.0 - kappa, efficiency=kap_X),
    ))
    net.add_edge(Edge(
        source_id=maturity.id, target_id=reproduction.id,
        name="Reproduction allocation",
        transport_type=TransportType.THRESHOLD,
        params=ep(rate_constant=v, threshold=E_Hp, efficiency=kap_R),
    ))

    return net


def create_daphnia_magna() -> TransportNetwork:
    """Daphnia magna (water flea) — AmP parameters."""
    return _create_organism_kdeb(
        name="Daphnia magna (kDEB)",
        p_Am=313.17,        # J/d/cm²
        v=0.1858,           # cm/d
        kappa=0.5809,
        p_M=1200.0,         # J/d/cm³
        E_G=4400.0,         # J/cm³
        T_A=6400.0,         # K
        E_Hb=0.0546,        # J
        E_Hp=1.09,          # J
        kap_X=0.9,
        kap_R=0.95,
        E0=5.0,
        V0=0.0001,
    )


def create_mytilus_edulis() -> TransportNetwork:
    """Mytilus edulis (blue mussel) — AmP parameters, Saraiva et al. (2011)."""
    return _create_organism_kdeb(
        name="Mytilus edulis (kDEB)",
        p_Am=11.07,          # J/d/cm²
        v=0.061,             # cm/d
        kappa=0.9965,
        p_M=2.65,            # J/d/cm³
        E_G=2348.0,          # J/cm³
        T_A=7022.0,          # K
        E_Hb=2.3e-7,         # J
        E_Hp=0.558,          # J
        kap_X=0.949,
        kap_R=0.95,
        E0=2.0,
        V0=0.0001,
    )


def create_danio_rerio() -> TransportNetwork:
    """Danio rerio (zebrafish) — AmP parameters, Augustine et al. (2011)."""
    return _create_organism_kdeb(
        name="Danio rerio (kDEB)",
        p_Am=150.72,         # J/d/cm²
        v=0.0196,            # cm/d
        kappa=0.3576,
        p_M=243.0,           # J/d/cm³
        E_G=5267.0,          # J/cm³
        T_A=8000.0,          # K
        E_Hb=0.793,          # J
        E_Hp=2361.0,         # J
        kap_X=0.8,
        kap_R=0.95,
        E0=20.0,
        V0=0.0001,
    )


def create_oncorhynchus_mykiss() -> TransportNetwork:
    """Oncorhynchus mykiss (rainbow trout) — AmP parameters."""
    return _create_organism_kdeb(
        name="Oncorhynchus mykiss (kDEB)",
        p_Am=2441.6,         # J/d/cm²
        v=0.0327,            # cm/d
        kappa=0.6194,
        p_M=343.9,           # J/d/cm³
        E_G=5258.0,          # J/cm³
        T_A=8000.0,          # K
        E_Hb=44.31,          # J
        E_Hp=5.87e6,         # J
        kap_X=0.8,
        kap_R=0.95,
        E0=100.0,
        V0=0.001,
    )


def create_lumbricus_terrestris() -> TransportNetwork:
    """Lumbricus terrestris (earthworm) — AmP parameters."""
    return _create_organism_kdeb(
        name="Lumbricus terrestris (kDEB)",
        p_Am=1617.5,         # J/d/cm²
        v=0.0537,            # cm/d
        kappa=0.9543,
        p_M=1360.0,          # J/d/cm³
        E_G=4180.0,          # J/cm³
        T_A=6594.0,          # K
        E_Hb=2.946,          # J
        E_Hp=1141.0,         # J
        kap_X=0.8,
        kap_R=0.475,
        E0=50.0,
        V0=0.001,
    )


# Template id → factory, plus the metadata the picker shows.
TEMPLATES = {
    "kdeb": {
        "factory": create_standard_kdeb,
        "name": "Standard kDEB",
        "description": "Classic DEB model with the κ-rule — the reference implementation.",
        "category": "template",
    },
    "tdeb_repro": {
        "factory": create_tdeb_with_reproduction,
        "name": "tDEB with reproduction",
        "description": "Transport network without a fixed κ — energy flows by local gradients and signals.",
        "category": "template",
    },
    "daphnia_magna": {
        "factory": create_daphnia_magna,
        "name": "Daphnia magna",
        "description": "Water flea — freshwater crustacean, a classic ecotoxicological model organism.",
        "category": "organism",
    },
    "mytilus_edulis": {
        "factory": create_mytilus_edulis,
        "name": "Mytilus edulis",
        "description": "Blue mussel — marine bivalve filter feeder.",
        "category": "organism",
    },
    "danio_rerio": {
        "factory": create_danio_rerio,
        "name": "Danio rerio",
        "description": "Zebrafish — freshwater fish, model organism in developmental biology.",
        "category": "organism",
    },
    "oncorhynchus_mykiss": {
        "factory": create_oncorhynchus_mykiss,
        "name": "Oncorhynchus mykiss",
        "description": "Rainbow trout — large freshwater fish, important in aquaculture.",
        "category": "organism",
    },
    "lumbricus_terrestris": {
        "factory": create_lumbricus_terrestris,
        "name": "Lumbricus terrestris",
        "description": "Earthworm — terrestrial oligochaete, important for soil ecology.",
        "category": "organism",
    },
}


def list_templates() -> List[dict]:
    """Template catalogue for the picker, without the factory callables."""
    return [
        {"id": tid, "name": t["name"], "description": t["description"], "category": t["category"]}
        for tid, t in TEMPLATES.items()
    ]


def build_template(template_id: str) -> Optional[TransportNetwork]:
    """Instantiate a template by id, or None if the id is unknown."""
    entry = TEMPLATES.get(template_id)
    return entry["factory"]() if entry else None
