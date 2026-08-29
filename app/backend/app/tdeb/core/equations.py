"""
tDEB Equation Sets
==================
Every formula the simulator evaluates — transport kinetics, the Arrhenius
correction, somatic maintenance, the efficiency multiplier and the
non-negativity clamp — lives here as an editable expression string.

The upstream simulator kept these in a single module-level dict backed by a
JSON file on disk, so editing a formula changed it for everyone using the
server.  AdvanDEB is multi-user, so instead an :class:`EquationSet` is an
explicit object that gets threaded through flux computation; the API layer
builds one per user from the defaults plus that user's stored overrides.
"""

from __future__ import annotations

import copy
import io
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from asteval import Interpreter


DEFAULT_PATH = Path(__file__).parent / "default_equations.json"

# Sections a user is allowed to override.  ``ode_rule`` is deliberately absent:
# it documents the structural accumulation rule, which the solver implements in
# code, so accepting edits there would promise something we do not honour.
EDITABLE_SECTIONS = (
    "transport",
    "arrhenius",
    "maintenance",
    "efficiency",
    "non_negativity",
)

# Every variable name the evaluator recognises, used for validation and for the
# hint appended to NameErrors.
KNOWN_VARS = [
    "X_source", "X_target", "T", "T_corr", "signal",
    "k", "V_max", "K_m", "kappa", "threshold", "eta",
    "n", "s", "T_ref", "T_A",
    "maintenance_rate", "X_value", "flux", "dydt",
    "sum_incoming", "sum_outgoing", "maintenance",
]

_MATH_NAMES = ["sin", "cos", "tan", "exp", "log", "log10", "sqrt", "abs", "pi", "e"]

_defaults_cache: Optional[Dict[str, Any]] = None


def load_defaults() -> Dict[str, Any]:
    """Return a deep copy of the shipped default equations."""
    global _defaults_cache
    if _defaults_cache is None:
        with open(DEFAULT_PATH, "r", encoding="utf-8") as f:
            _defaults_cache = json.load(f)
    return copy.deepcopy(_defaults_cache)


def _make_interpreter() -> Interpreter:
    """
    A minimal asteval interpreter with the maths functions formulas may use.

    ``err_writer`` is discarded: a formula that fails is reported through the
    return value or the error list, and asteval's default is to also print a
    traceback to stderr, which would spam the server log on every ODE step.
    """
    aeval = Interpreter(minimal=True, err_writer=io.StringIO())
    for name in _MATH_NAMES:
        val = getattr(np, name, None)
        if val is not None:
            aeval.symtable[name] = val
    # Python builtins — np.min/np.max take an array, not two scalars.
    aeval.symtable["min"] = min
    aeval.symtable["max"] = max
    return aeval


def _clean_error_message(error_tuple: tuple) -> str:
    """
    Turn an asteval error into a single readable line.

    ``get_error()`` returns e.g. ``('NameError', '  2*k*X\\n     ^^^^\\n
    NameError: name 'X' is not defined')`` — we keep the last meaningful line
    and, for NameErrors, append the list of variables that *are* available.
    """
    err_type, raw = error_tuple
    lines = [ln for ln in raw.split("\n") if ln.strip()]
    msg = lines[-1] if lines else raw

    prefix = f"{err_type}: "
    if msg.startswith(prefix):
        msg = msg[len(prefix):]

    # "(<unknown>, line 1)" is noise for a one-line expression.
    msg = re.sub(r"\s*\(<unknown>,\s*line\s*\d+\)\s*$", "", msg)

    if err_type == "NameError":
        msg += f"  [available: {', '.join(KNOWN_VARS)}]"

    return msg


def validate_formula(formula: str, extra_vars: Optional[List[str]] = None) -> Tuple[bool, str]:
    """
    Evaluate ``formula`` with every known variable set to 1.0.

    Returns ``(is_valid, error_message)``.  An empty formula is valid — it just
    means "no flux".
    """
    if not formula or not formula.strip():
        return True, ""
    try:
        aeval = _make_interpreter()
        for name in list(KNOWN_VARS) + list(extra_vars or []):
            aeval.symtable[name] = 1.0
        aeval.symtable["True"] = True
        aeval.symtable["False"] = False

        result = aeval(formula)
        if aeval.error:
            return False, _clean_error_message(aeval.error[0].get_error())
        if result is None:
            return False, "Expression returned no value"
        return True, ""
    except Exception as e:  # noqa: BLE001 — surface whatever asteval raised
        return False, str(e)


class EquationSet:
    """
    A resolved set of formulas plus the evaluator that runs them.

    One instance is built per simulation run.  It owns a single asteval
    interpreter and a cache of parsed ASTs keyed by formula string, so a formula
    is parsed once per run rather than once per ODE step — the same optimisation
    the upstream code did per-edge, but shared across the whole network.
    """

    def __init__(self, data: Optional[Dict[str, Any]] = None):
        self.data: Dict[str, Any] = data if data is not None else load_defaults()
        self._aeval = _make_interpreter()
        self._ast_cache: Dict[str, Any] = {}

    # ── formula lookup ────────────────────────────────────────────────

    def transport_formula(self, transport_type: str) -> str:
        entry = self.data.get("transport", {}).get(transport_type, {})
        return entry.get("formula", "")

    def arrhenius_formula(self) -> str:
        return self.data.get("arrhenius", {}).get(
            "formula", "exp(T_A / T_ref - T_A / T)"
        )

    def maintenance_formula(self) -> str:
        return self.data.get("maintenance", {}).get(
            "formula", "maintenance_rate * X_value * T_corr"
        )

    def efficiency_formula(self) -> str:
        return self.data.get("efficiency", {}).get("formula", "flux * eta")

    def non_negativity_enabled(self) -> bool:
        return bool(self.data.get("non_negativity", {}).get("enabled", True))

    # ── evaluation ────────────────────────────────────────────────────

    def _parse(self, formula: str):
        """Parse and cache ``formula``; returns None if it will not compile."""
        if formula not in self._ast_cache:
            try:
                self._ast_cache[formula] = self._aeval.parse(formula)
            except Exception:  # noqa: BLE001 — a bad formula falls back to default
                self._ast_cache[formula] = None
            self._aeval.error = []
        return self._ast_cache[formula]

    def evaluate(self, formula: str, variables: Dict[str, float]) -> Optional[float]:
        """
        Evaluate ``formula`` with ``variables`` bound.

        Returns ``None`` when the formula is empty, will not parse, or errors at
        runtime — callers decide what to substitute.
        """
        if not formula:
            return None
        node = self._parse(formula)
        if node is None:
            return None

        st = self._aeval.symtable
        st.update(variables)
        # with_raise=False makes asteval collect failures in .error rather than
        # raising; the try/except keeps us safe regardless of asteval version,
        # since a bad user formula must degrade the flux, not abort the run.
        try:
            result = self._aeval.run(node, with_raise=False)
        except Exception:  # noqa: BLE001
            self._aeval.error = []
            return None
        if self._aeval.error or result is None:
            self._aeval.error = []
            return None
        try:
            return float(result)
        except (TypeError, ValueError):
            return None


def merge_overrides(overrides: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Layer a user's stored overrides on top of the shipped defaults.

    Only formula strings (and the non-negativity ``enabled`` flag) are taken
    from the overrides — descriptions, LaTeX and variable lists always come from
    the defaults so stored data cannot rewrite the UI's explanatory text.
    """
    result = load_defaults()
    if not overrides:
        return result

    for section in EDITABLE_SECTIONS:
        incoming = overrides.get(section)
        if not isinstance(incoming, dict):
            continue

        if section == "transport":
            for key, entry in incoming.items():
                if key in result["transport"] and isinstance(entry, dict):
                    formula = entry.get("formula")
                    if isinstance(formula, str):
                        result["transport"][key]["formula"] = formula
            continue

        target = result.setdefault(section, {})
        formula = incoming.get("formula")
        if isinstance(formula, str):
            target["formula"] = formula
        if section == "non_negativity" and "enabled" in incoming:
            target["enabled"] = bool(incoming["enabled"])

    return result


def extract_overrides(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Reduce a full equation document to just the parts that differ from defaults.

    Keeps stored documents small and means a later change to the shipped
    defaults reaches users who never edited that formula.
    """
    defaults = load_defaults()
    out: Dict[str, Any] = {}

    for key, entry in (data.get("transport") or {}).items():
        default_entry = defaults.get("transport", {}).get(key)
        if not default_entry or not isinstance(entry, dict):
            continue
        formula = entry.get("formula")
        if isinstance(formula, str) and formula != default_entry.get("formula"):
            out.setdefault("transport", {})[key] = {"formula": formula}

    for section in ("arrhenius", "maintenance", "efficiency", "non_negativity"):
        entry = data.get(section)
        if not isinstance(entry, dict):
            continue
        default_entry = defaults.get(section, {})
        diff: Dict[str, Any] = {}
        formula = entry.get("formula")
        if isinstance(formula, str) and formula != default_entry.get("formula"):
            diff["formula"] = formula
        if section == "non_negativity":
            enabled = entry.get("enabled")
            if enabled is not None and bool(enabled) != bool(default_entry.get("enabled", True)):
                diff["enabled"] = bool(enabled)
        if diff:
            out[section] = diff

    return out
