"""
tDEB Transport Kinetics
=======================
Edges are transport channels between compartments.  Each carries a kinetic law
that determines its flux; the law itself is an expression string resolved from
the active :class:`EquationSet`, so kinetics can be edited without code changes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Tuple

import numpy as np

from .equations import EquationSet, validate_formula


class TransportType(str, Enum):
    LINEAR = "linear"                       # J = k * X_source
    MICHAELIS_MENTEN = "michaelis_menten"   # J = Vmax * X / (X + Km)
    GRADIENT = "gradient"                   # J = k * (X_source - X_target)
    KAPPA_SPLIT = "kappa_split"             # J = κ * mobilization flux
    REGULATED = "regulated"                 # J = Vmax * X/(X+Km) * σ(signal)
    THRESHOLD = "threshold"                 # J = k * max(0, X - threshold)
    FIXED = "fixed"                         # J = constant rate
    CUSTOM = "custom"                       # user-supplied expression


@dataclass
class EdgeParams:
    """Parameters for transport kinetics."""
    rate_constant: float = 1.0         # k [1/d]
    V_max: float = 1.0                 # Maximum flux [J/d]
    K_m: float = 1.0                   # Half-saturation constant [J]
    kappa: float = 0.8                 # Allocation fraction
    threshold: float = 0.0             # Activation threshold
    efficiency: float = 1.0            # Conversion efficiency (0-1)
    hill_coeff: float = 1.0            # Hill coefficient for cooperativity
    signal_strength: float = 1.0       # Regulatory signal multiplier
    custom_formula: str = ""           # User expression for CUSTOM type

    # Arrhenius
    T_ref: float = 293.15
    T_A: float = 8000.0


@dataclass
class Edge:
    """A transport channel between two nodes in the tDEB network."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    source_id: str = ""
    target_id: str = ""
    name: str = "transport"
    transport_type: TransportType = TransportType.LINEAR
    params: EdgeParams = field(default_factory=EdgeParams)

    # Last computed flux, kept for visualization
    current_flux: float = 0.0

    def _formula(self, equations: EquationSet) -> str:
        if self.transport_type == TransportType.CUSTOM:
            return self.params.custom_formula
        return equations.transport_formula(self.transport_type.value)

    def compute_flux(self, equations: EquationSet,
                     source_value: float, target_value: float,
                     temperature: float = 293.15,
                     signal: float = 1.0) -> float:
        """
        Flux along this edge under the given kinetic law.

        ``source_value``/``target_value`` are the current states of the endpoint
        compartments, ``temperature`` is in K and ``signal`` is the regulatory
        signal in [0,1].  Returns the flux in [J/d] (or mol/d), after the
        efficiency multiplier.
        """
        p = self.params

        T_corr = equations.evaluate(
            equations.arrhenius_formula(),
            {"T_A": p.T_A, "T_ref": p.T_ref, "T": temperature},
        )
        if T_corr is None:
            T_corr = float(np.exp(p.T_A / p.T_ref - p.T_A / temperature))

        variables = {
            "X_source": source_value,
            "X_target": target_value,
            "T": temperature,
            "T_corr": T_corr,
            "signal": signal,
            "k": p.rate_constant,
            "V_max": p.V_max,
            "K_m": p.K_m,
            "kappa": p.kappa,
            "threshold": p.threshold,
            "eta": p.efficiency,
            "n": p.hill_coeff,
            "s": p.signal_strength,
            "T_ref": p.T_ref,
            "T_A": p.T_A,
        }

        flux = equations.evaluate(self._formula(equations), variables)
        if flux is None:
            flux = 0.0

        variables["flux"] = flux
        with_efficiency = equations.evaluate(equations.efficiency_formula(), variables)
        self.current_flux = flux * p.efficiency if with_efficiency is None else with_efficiency
        return self.current_flux

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "name": self.name,
            "transport_type": self.transport_type.value,
            "current_flux": self.current_flux,
            "params": {
                "rate_constant": self.params.rate_constant,
                "V_max": self.params.V_max,
                "K_m": self.params.K_m,
                "kappa": self.params.kappa,
                "threshold": self.params.threshold,
                "efficiency": self.params.efficiency,
                "hill_coeff": self.params.hill_coeff,
                "signal_strength": self.params.signal_strength,
                "custom_formula": self.params.custom_formula,
                "T_ref": self.params.T_ref,
                "T_A": self.params.T_A,
            },
        }

    @staticmethod
    def validate_formula(formula: str) -> Tuple[bool, str]:
        """Check a custom flux expression against dummy values."""
        return validate_formula(formula)

    @classmethod
    def from_dict(cls, d: dict) -> "Edge":
        raw = d.get("params") or {}
        known = {k: v for k, v in raw.items() if k in EdgeParams.__dataclass_fields__}
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            source_id=d["source_id"],
            target_id=d["target_id"],
            name=d.get("name", "transport"),
            transport_type=TransportType(d.get("transport_type", "linear")),
            params=EdgeParams(**known),
        )
