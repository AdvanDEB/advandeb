"""
tDEB ODE Solver
===============
Wraps ``scipy.integrate.solve_ivp`` with two modes:

* :meth:`Solver.run` — solve the whole horizon and return the time series.
* :class:`StreamingRun` — advance one output interval at a time so a caller can
  stream snapshots to the browser.

Both are synchronous and CPU-bound; the API layer runs them off the event loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
from scipy.integrate import solve_ivp

from .equations import EquationSet
from .network import EnvironmentParams, TransportNetwork


SOLVER_METHODS = ("LSODA", "BDF", "Radau", "RK45", "RK23")

# LSODA is the default rather than RK45 (which the upstream prototype used).
# DEB transport networks are routinely stiff: maintenance and mobilisation rates
# differ by orders of magnitude, so compartments equilibrate on very different
# timescales. On the Daphnia magna template over 100 days, explicit RK45 needs
# ~254,000 right-hand-side evaluations where LSODA needs ~650 for the same
# trajectory to six significant figures — 20 s versus 0.06 s. LSODA switches
# between non-stiff and stiff internally, so it stays a safe general default.
DEFAULT_METHOD = "LSODA"

# Ceiling on output points per run.  A simulation is charged to a shared web
# process, so an unbounded t_end/dt_output ratio would let one request pin a
# core for minutes; requests above this are rejected rather than truncated.
MAX_OUTPUT_POINTS = 100_000


@dataclass
class SimulationParams:
    """Simulation configuration."""
    t_start: float = 0.0
    t_end: float = 365.0            # 1 year default
    dt_output: float = 1.0          # Output interval [days]
    method: str = DEFAULT_METHOD
    rtol: float = 1e-6
    atol: float = 1e-9
    # Cap the internal step at one output interval so a threshold-activated
    # channel cannot be stepped straight over. ``None`` lets the solver choose.
    max_step: Optional[float] = None

    def effective_max_step(self) -> float:
        return self.max_step if self.max_step is not None else self.dt_output

    def validate(self) -> None:
        """Reject configurations that are unsolvable or unreasonably large."""
        if self.method not in SOLVER_METHODS:
            raise ValueError(
                f"Unknown solver method '{self.method}'. "
                f"Expected one of: {', '.join(SOLVER_METHODS)}"
            )
        if self.dt_output <= 0:
            raise ValueError("Output interval must be greater than zero")
        if self.t_end <= self.t_start:
            raise ValueError("Simulation end time must be after the start time")

        n_points = (self.t_end - self.t_start) / self.dt_output
        if n_points > MAX_OUTPUT_POINTS:
            raise ValueError(
                f"Requested {int(n_points):,} output points, which exceeds the "
                f"{MAX_OUTPUT_POINTS:,} limit. Increase the output interval or "
                f"shorten the simulation."
            )

    def output_times(self) -> np.ndarray:
        return np.arange(self.t_start, self.t_end + self.dt_output, self.dt_output)

    def to_dict(self) -> dict:
        return {
            "t_start": self.t_start,
            "t_end": self.t_end,
            "dt_output": self.dt_output,
            "method": self.method,
            "rtol": self.rtol,
            "atol": self.atol,
            "max_step": self.effective_max_step(),
        }


@dataclass
class SimulationResult:
    """Container for simulation results."""
    time: np.ndarray = field(default_factory=lambda: np.array([]))
    states: np.ndarray = field(default_factory=lambda: np.array([]))
    labels: List[str] = field(default_factory=list)
    fluxes: Dict[str, List[float]] = field(default_factory=dict)
    success: bool = True
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "time": self.time.tolist(),
            "states": {
                label: self.states[:, i].tolist()
                for i, label in enumerate(self.labels)
            } if len(self.states) else {},
            "fluxes": self.fluxes,
            "success": self.success,
            "message": self.message,
            "n_points": len(self.time),
        }


class Solver:
    """ODE solver for tDEB transport networks."""

    def __init__(self, network: TransportNetwork,
                 equations: EquationSet,
                 params: Optional[SimulationParams] = None):
        self.network = network
        self.equations = equations
        self.params = params or SimulationParams()

    def _rhs(self, t: float, y: np.ndarray) -> np.ndarray:
        return self.network.derivatives(t, y, self.equations)

    def run(self, env: Optional[EnvironmentParams] = None) -> SimulationResult:
        """Solve the full horizon and return every state and flux time series."""
        self.params.validate()
        self.network.apply_environment(env)

        y0 = self.network.get_initial_state()
        labels = self.network.get_state_labels()

        if len(y0) == 0:
            return SimulationResult(
                success=False,
                message="The model has no state compartments — add at least one non-food node.",
                labels=labels,
            )

        sol = solve_ivp(
            fun=self._rhs,
            t_span=(self.params.t_start, self.params.t_end),
            y0=y0,
            method=self.params.method,
            t_eval=self.params.output_times(),
            rtol=self.params.rtol,
            atol=self.params.atol,
            max_step=self.params.effective_max_step(),
        )

        if not sol.success:
            return SimulationResult(success=False, message=sol.message, labels=labels)

        # Replay the solution to recover fluxes at each output time.
        flux_history: Dict[str, List[float]] = {eid: [] for eid in self.network.edges}
        for i in range(len(sol.t)):
            self.network.set_state_vector(sol.y[:, i])
            for eid, flux in self.network.compute_fluxes(self.equations).items():
                flux_history[eid].append(flux)

        # Key fluxes by edge name for display. Duplicate names would collide, so
        # disambiguate with the edge id rather than silently dropping a series.
        named_fluxes: Dict[str, List[float]] = {}
        for eid, values in flux_history.items():
            name = self.network.edges[eid].name or "transport"
            if name in named_fluxes:
                name = f"{name} [{eid}]"
            named_fluxes[name] = values

        return SimulationResult(
            time=sol.t,
            states=sol.y.T,  # (n_times, n_states)
            labels=labels,
            fluxes=named_fluxes,
            success=True,
            message="Simulation completed successfully",
        )


class StreamingRun:
    """
    Step-at-a-time integration for WebSocket streaming.

    Each :meth:`step` integrates one output interval and returns a snapshot of
    node values and edge fluxes, or ``None`` once the horizon is reached.
    """

    def __init__(self, network: TransportNetwork,
                 equations: EquationSet,
                 params: SimulationParams,
                 env: Optional[EnvironmentParams] = None):
        params.validate()
        self.network = network
        self.equations = equations
        self.params = params

        self.network.apply_environment(env)
        self.t_points = params.output_times()
        self.current_y = self.network.get_initial_state()
        self.index = 0
        self.finished = len(self.t_points) < 2 or len(self.current_y) == 0

    @property
    def total_steps(self) -> int:
        return max(len(self.t_points) - 1, 0)

    def step(self) -> Optional[dict]:
        """Advance one output interval; ``None`` when the run is complete."""
        if self.finished or self.index >= self.total_steps:
            self.finished = True
            return None

        t0 = self.t_points[self.index]
        t1 = self.t_points[self.index + 1]

        sol = solve_ivp(
            fun=lambda t, y: self.network.derivatives(t, y, self.equations),
            t_span=(t0, t1),
            y0=self.current_y,
            method=self.params.method,
            rtol=self.params.rtol,
            atol=self.params.atol,
        )

        if not sol.success:
            self.finished = True
            return {"error": sol.message, "time": float(t0)}

        self.current_y = sol.y[:, -1]
        self.network.set_state_vector(self.current_y)
        fluxes = self.network.compute_fluxes(self.equations)

        self.index += 1

        return {
            "time": float(t1),
            "progress": float(self.index / self.total_steps),
            "nodes": {
                nid: {
                    "value": float(self.network.nodes[nid].value),
                    "name": self.network.nodes[nid].name,
                }
                for nid in self.network._state_node_ids
            },
            "flows": {
                eid: {"flux": float(flux), "name": self.network.edges[eid].name}
                for eid, flux in fluxes.items()
            },
        }
