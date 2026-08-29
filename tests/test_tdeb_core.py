"""Unit tests for the tDEB transport-network simulation core.

In-process only — no database, no HTTP. These pin the parts of the port that
would regress silently: the ODE assembly from graph topology, the guard rails on
solver configuration, and the rule that a user-supplied formula must degrade
rather than abort a simulation.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app", "backend"))

from app.tdeb.core import (  # noqa: E402
    EnvironmentParams, EquationSet, SimulationParams, Solver, StreamingRun,
    TransportNetwork, TransportType, Edge, EdgeParams, NodeType,
    build_template, extract_overrides, list_templates, load_defaults,
    merge_overrides, validate_formula,
)
from app.tdeb.core.nodes import (  # noqa: E402
    create_food_node, create_reserve_node, create_structure_node,
)


TEMPLATE_IDS = [t["id"] for t in list_templates()]


# ─── Templates ────────────────────────────────────────────────────────

@pytest.mark.parametrize("template_id", TEMPLATE_IDS)
def test_every_template_solves(template_id):
    """Each shipped template must integrate cleanly over a short horizon."""
    network = build_template(template_id)
    result = Solver(network, EquationSet(), SimulationParams(t_end=60.0)).run(
        EnvironmentParams()
    )
    assert result.success, result.message
    assert len(result.time) == 61
    assert result.states.shape[0] == 61
    # Food is a boundary condition, so it is never a state variable.
    assert "Food (X)" not in result.labels


def test_unknown_template_returns_none():
    assert build_template("not_a_template") is None


# ─── ODE assembly ─────────────────────────────────────────────────────

def _two_node_network(transport_type, params):
    net = TransportNetwork(name="pair")
    source = create_reserve_node(E0=100.0)
    target = create_structure_node(V0=1.0, p_M=0.0)
    net.add_node(source)
    net.add_node(target)
    net.add_edge(Edge(source_id=source.id, target_id=target.id,
                      name="flow", transport_type=transport_type, params=params))
    return net, source, target


def test_flux_moves_mass_from_source_to_target():
    """Whatever leaves the source arrives at the target — the graph is conserved."""
    net, source, target = _two_node_network(
        TransportType.LINEAR, EdgeParams(rate_constant=0.1, T_A=0.0),
    )
    eqs = EquationSet()
    y = net.get_initial_state()
    dydt = net.derivatives(0.0, y, eqs)

    idx = {nid: i for i, nid in enumerate(net._state_node_ids)}
    assert dydt[idx[source.id]] == pytest.approx(-dydt[idx[target.id]])
    assert dydt[idx[source.id]] < 0


def test_maintenance_is_drawn_from_structure_only():
    """p_M on a non-structure compartment must not silently drain it."""
    net = TransportNetwork(name="maint")
    structure = create_structure_node(V0=10.0, p_M=2.0)
    reserve = create_reserve_node(E0=10.0)
    reserve.params.maintenance_rate = 2.0   # set, but should be ignored
    structure.params.T_A = 0.0
    reserve.params.T_A = 0.0
    net.add_node(structure)
    net.add_node(reserve)

    dydt = net.derivatives(0.0, net.get_initial_state(), EquationSet())
    idx = {nid: i for i, nid in enumerate(net._state_node_ids)}
    assert dydt[idx[structure.id]] == pytest.approx(-20.0)
    assert dydt[idx[reserve.id]] == pytest.approx(0.0)


def test_non_negativity_clamp_holds_states_at_zero():
    """
    An empty compartment must not be driven negative.

    The drain here is a fixed-rate channel rather than maintenance: maintenance
    is proportional to the state, so it is already zero at V = 0 and would not
    exercise the clamp at all.
    """
    net = TransportNetwork(name="clamp")
    empty = create_structure_node(V0=0.0, p_M=0.0)
    sink = create_reserve_node(E0=0.0)
    empty.params.T_A = 0.0
    net.add_node(empty)
    net.add_node(sink)
    net.add_edge(Edge(
        source_id=empty.id, target_id=sink.id, name="drain",
        transport_type=TransportType.FIXED,
        params=EdgeParams(rate_constant=3.0, T_A=0.0),
    ))

    idx = {nid: i for i, nid in enumerate(net._state_node_ids)}
    y0 = net.get_initial_state()

    clamped = net.derivatives(0.0, y0, EquationSet())
    assert clamped[idx[empty.id]] == 0.0

    loose = EquationSet(merge_overrides({"non_negativity": {"enabled": False}}))
    assert net.derivatives(0.0, y0, loose)[idx[empty.id]] == pytest.approx(-3.0)


def test_food_density_reaches_food_compartments():
    """
    The environment's functional response must actually drive assimilation.

    Food nodes are excluded from the state vector, so nothing in the integration
    loop updates them — ``apply_environment`` is the only path by which the
    chosen ``f`` influences a run.
    """
    def final_structure(f):
        net = build_template("kdeb")
        result = Solver(net, EquationSet(), SimulationParams(t_end=50.0)).run(
            EnvironmentParams(food_density=f)
        )
        assert result.success
        return result.to_dict()["states"]["Structure (V)"][-1]

    assert final_structure(0.1) < final_structure(1.0)


# ─── Solver configuration ─────────────────────────────────────────────

def test_rejects_unknown_solver_method():
    with pytest.raises(ValueError, match="Unknown solver method"):
        SimulationParams(method="Euler").validate()


def test_rejects_non_positive_output_interval():
    with pytest.raises(ValueError, match="greater than zero"):
        SimulationParams(dt_output=0.0).validate()


def test_rejects_end_before_start():
    with pytest.raises(ValueError, match="after the start"):
        SimulationParams(t_start=10.0, t_end=1.0).validate()


def test_rejects_absurd_point_counts():
    """A shared web process must not accept a run that would pin a core."""
    with pytest.raises(ValueError, match="exceeds"):
        SimulationParams(t_end=1e9, dt_output=0.001).validate()


def test_network_with_no_state_compartments_reports_failure():
    net = TransportNetwork(name="food only")
    net.add_node(create_food_node())
    result = Solver(net, EquationSet(), SimulationParams(t_end=10.0)).run(None)
    assert not result.success
    assert "no state compartments" in result.message


# ─── Formulas ─────────────────────────────────────────────────────────

def test_validate_formula_accepts_known_variables():
    assert validate_formula("k * X_source * T_corr") == (True, "")


def test_validate_formula_rejects_unknown_name_and_lists_alternatives():
    valid, error = validate_formula("2 * k * X")
    assert not valid
    assert "X_source" in error


def test_validate_formula_rejects_syntax_error():
    valid, error = validate_formula("k * (")
    assert not valid
    assert error


@pytest.mark.parametrize("formula", ["k * bogus", "k * (", "k / 0", "'text'"])
def test_broken_formula_evaluates_to_none(formula):
    assert EquationSet().evaluate(formula, {"k": 1.0}) is None


def test_broken_kinetics_degrade_instead_of_aborting_the_run():
    """
    A user can save a formula that does not evaluate. The run must complete with
    that channel contributing no flux, rather than raising out of the solver.
    """
    eqs = EquationSet(merge_overrides(
        {"transport": {"kappa_split": {"formula": "k * undefined_name"}}}
    ))
    result = Solver(build_template("kdeb"), eqs, SimulationParams(t_end=20.0)).run(
        EnvironmentParams()
    )
    assert result.success, result.message


# ─── Equation overrides ───────────────────────────────────────────────

def test_overrides_replace_only_the_named_formula():
    merged = merge_overrides({"transport": {"linear": {"formula": "2 * k * X_source"}}})
    defaults = load_defaults()
    assert merged["transport"]["linear"]["formula"] == "2 * k * X_source"
    assert merged["transport"]["michaelis_menten"] == defaults["transport"]["michaelis_menten"]


def test_overrides_cannot_rewrite_explanatory_text():
    """Stored data supplies formulas; descriptions always come from defaults."""
    merged = merge_overrides({
        "transport": {"linear": {"formula": "k", "description": "spoofed", "latex": "x"}}
    })
    defaults = load_defaults()
    assert merged["transport"]["linear"]["description"] == defaults["transport"]["linear"]["description"]
    assert merged["transport"]["linear"]["latex"] == defaults["transport"]["linear"]["latex"]


def test_extract_overrides_stores_only_differences():
    doc = load_defaults()
    assert extract_overrides(doc) == {}

    doc["transport"]["linear"]["formula"] = "9 * k"
    doc["non_negativity"]["enabled"] = False
    assert extract_overrides(doc) == {
        "transport": {"linear": {"formula": "9 * k"}},
        "non_negativity": {"enabled": False},
    }


def test_ode_rule_is_not_an_override_target():
    """The accumulation rule is implemented in code, so it must not be editable."""
    merged = merge_overrides({"ode_rule": {"formula": "anything"}})
    assert merged["ode_rule"]["formula"] == load_defaults()["ode_rule"]["formula"]


# ─── Serialization ────────────────────────────────────────────────────

def test_round_trip_preserves_topology_and_parameters():
    original = build_template("tdeb_repro")
    restored = TransportNetwork.from_dict(original.to_dict())

    assert restored.name == original.name
    assert set(restored.nodes) == set(original.nodes)
    assert set(restored.edges) == set(original.edges)
    for eid, edge in original.edges.items():
        assert restored.edges[eid].params == edge.params
        assert restored.edges[eid].transport_type == edge.transport_type


def test_import_drops_edges_with_missing_endpoints():
    """A hand-edited or truncated file should still load, minus the bad edges."""
    doc = build_template("kdeb").to_dict()
    doc["edges"]["ghost"] = {
        "id": "ghost", "source_id": "nope", "target_id": "alsonope",
        "name": "dangling", "transport_type": "linear", "params": {},
    }
    restored = TransportNetwork.from_dict(doc)
    assert "ghost" not in restored.edges
    assert len(restored.edges) == 4


def test_import_ignores_unknown_parameter_keys():
    doc = build_template("kdeb").to_dict()
    for node in doc["nodes"].values():
        node["params"]["from_a_future_version"] = 1.0
    assert len(TransportNetwork.from_dict(doc).nodes) == 5


def test_adding_an_edge_to_a_missing_node_raises():
    net = TransportNetwork(name="x")
    node = net.add_node(create_reserve_node())
    with pytest.raises(ValueError, match="not in the network"):
        net.add_edge(Edge(source_id=node.id, target_id="absent"))


def test_removing_a_node_removes_its_edges():
    net = build_template("kdeb")
    reserve = next(n for n in net.nodes.values() if n.node_type == NodeType.RESERVE)
    net.remove_node(reserve.id)
    assert reserve.id not in net.nodes
    assert all(
        reserve.id not in (e.source_id, e.target_id) for e in net.edges.values()
    )


# ─── Streaming ────────────────────────────────────────────────────────

def test_streaming_run_yields_one_snapshot_per_interval():
    run = StreamingRun(
        build_template("kdeb"), EquationSet(),
        SimulationParams(t_end=5.0, dt_output=1.0), EnvironmentParams(),
    )
    snapshots = []
    while (snapshot := run.step()) is not None:
        snapshots.append(snapshot)

    assert len(snapshots) == 5
    assert snapshots[-1]["progress"] == pytest.approx(1.0)
    assert snapshots[-1]["time"] == pytest.approx(5.0)
    assert run.step() is None, "a finished run must keep returning None"


def test_streaming_snapshots_exclude_food_compartments():
    run = StreamingRun(
        build_template("kdeb"), EquationSet(),
        SimulationParams(t_end=2.0, dt_output=1.0), EnvironmentParams(),
    )
    names = {n["name"] for n in run.step()["nodes"].values()}
    assert "Food (X)" not in names
    assert "Structure (V)" in names
