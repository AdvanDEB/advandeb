"""
tDEB Node Types
===============
Each node is a compartment in the organism's energy budget: it holds a state
variable and defines whatever local metabolic cost that compartment carries.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from .equations import EquationSet


class NodeType(str, Enum):
    FOOD = "food"                   # External food source
    ASSIMILATION = "assimilation"   # Assimilation organ (gut)
    RESERVE = "reserve"             # Energy reserve (E)
    STRUCTURE = "structure"         # Structural volume (V)
    MATURITY = "maturity"           # Maturity level (E_H)
    REPRODUCTION = "reproduction"   # Reproduction buffer (E_R)
    GONAD = "gonad"                 # Gonad compartment
    DAMAGE = "damage"               # Damage / aging compartment
    TOXICANT = "toxicant"           # Internal toxicant concentration
    CUSTOM = "custom"               # User-defined compartment


@dataclass
class NodeParams:
    """Parameters for a network node."""
    # Metabolic costs
    maintenance_rate: float = 0.0      # Somatic maintenance rate [J/d/cm³]
    specific_cost: float = 0.0         # Specific cost of structure [J/cm³]
    max_capacity: float = 1e12         # Maximum storage capacity [J]

    # Arrhenius temperature dependence
    T_ref: float = 293.15              # Reference temperature [K] (20°C)
    T_A: float = 8000.0                # Arrhenius temperature [K]

    # Additional
    kappa: float = 0.8                 # Allocation fraction (kDEB compatibility)
    efficiency: float = 1.0            # Conversion efficiency


@dataclass
class Node:
    """A compartment in the tDEB transport network."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "unnamed"
    node_type: NodeType = NodeType.CUSTOM

    # State variable
    value: float = 0.0                 # Current energy/mass in node [J or mol]
    initial_value: float = 0.0         # Initial condition

    # Position for visualization
    x: float = 0.0
    y: float = 0.0

    params: NodeParams = field(default_factory=NodeParams)
    color: str = "#4A90D9"

    def maintenance_cost(self, equations: EquationSet, temperature: float = 293.15) -> float:
        """
        Somatic maintenance drawn from this compartment at ``temperature``.

        Both the Arrhenius correction and the maintenance law come from
        ``equations``; if either fails to evaluate we fall back to the standard
        DEB forms so a broken user formula degrades rather than crashes the run.
        """
        T_corr = equations.evaluate(
            equations.arrhenius_formula(),
            {"T_A": self.params.T_A, "T_ref": self.params.T_ref, "T": temperature},
        )
        if T_corr is None:
            T_corr = float(np.exp(self.params.T_A / self.params.T_ref
                                  - self.params.T_A / temperature))

        maint = equations.evaluate(
            equations.maintenance_formula(),
            {
                "T_corr": T_corr,
                "maintenance_rate": self.params.maintenance_rate,
                "X_value": self.value,
            },
        )
        if maint is None:
            return self.params.maintenance_rate * self.value * T_corr
        return maint

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "node_type": self.node_type.value,
            "value": self.value,
            "initial_value": self.initial_value,
            "x": self.x,
            "y": self.y,
            "color": self.color,
            "params": {
                "maintenance_rate": self.params.maintenance_rate,
                "specific_cost": self.params.specific_cost,
                "max_capacity": self.params.max_capacity,
                "T_ref": self.params.T_ref,
                "T_A": self.params.T_A,
                "kappa": self.params.kappa,
                "efficiency": self.params.efficiency,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        raw = d.get("params") or {}
        # Ignore unknown keys so an imported file from a newer/older build loads.
        known = {k: v for k, v in raw.items() if k in NodeParams.__dataclass_fields__}
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            name=d.get("name", "unnamed"),
            node_type=NodeType(d.get("node_type", "custom")),
            value=float(d.get("value", 0.0)),
            initial_value=float(d.get("initial_value", 0.0)),
            x=float(d.get("x", 0.0)),
            y=float(d.get("y", 0.0)),
            color=d.get("color", "#4A90D9"),
            params=NodeParams(**known),
        )


# ─── Predefined node factories ────────────────────────────────────────

def create_food_node(f: float = 1.0, x: float = 50, y: float = 50) -> Node:
    """Food source with functional response f ∈ [0,1]."""
    return Node(
        name="Food (X)", node_type=NodeType.FOOD,
        value=f, initial_value=f,
        x=x, y=y, color="#66BB6A",
    )


def create_reserve_node(E0: float = 100.0, x: float = 300, y: float = 200) -> Node:
    """Energy reserve compartment."""
    return Node(
        name="Reserve (E)", node_type=NodeType.RESERVE,
        value=E0, initial_value=E0,
        x=x, y=y, color="#FFA726",
        params=NodeParams(maintenance_rate=0.0),
    )


def create_structure_node(V0: float = 0.01, p_M: float = 18.0,
                          E_G: float = 2800.0,
                          x: float = 200, y: float = 400) -> Node:
    """Structural volume compartment."""
    return Node(
        name="Structure (V)", node_type=NodeType.STRUCTURE,
        value=V0, initial_value=V0,
        x=x, y=y, color="#42A5F5",
        params=NodeParams(maintenance_rate=p_M, specific_cost=E_G),
    )


def create_maturity_node(EH0: float = 0.0, x: float = 400, y: float = 400) -> Node:
    """Maturity level compartment."""
    return Node(
        name="Maturity (E_H)", node_type=NodeType.MATURITY,
        value=EH0, initial_value=EH0,
        x=x, y=y, color="#AB47BC",
        params=NodeParams(maintenance_rate=0.0),
    )


def create_reproduction_node(ER0: float = 0.0, x: float = 500, y: float = 200) -> Node:
    """Reproduction buffer compartment."""
    return Node(
        name="Reproduction (E_R)", node_type=NodeType.REPRODUCTION,
        value=ER0, initial_value=ER0,
        x=x, y=y, color="#EF5350",
        params=NodeParams(maintenance_rate=0.0),
    )


def create_gonad_node(x: float = 600, y: float = 400) -> Node:
    """Gonad compartment for gamete production."""
    return Node(
        name="Gonad", node_type=NodeType.GONAD,
        value=0.0, initial_value=0.0,
        x=x, y=y, color="#EC407A",
    )
