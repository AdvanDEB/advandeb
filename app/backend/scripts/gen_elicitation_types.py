#!/usr/bin/env python3
"""Generate the elicitation and enrolment APIs' TypeScript types from their
pydantic models.

The client and server used to describe the same payloads twice, by hand, and
the copies drifted three ways at once: the evidence task existed on the server
and not in the client's `TaskType`; the client gated on calibration fields
(`required`, `complete`, `passed`) the server never sent; and the calibration
flow posted to an endpoint that did not exist. Every one of them failed
silently. One definition, generated, is what stops that.

Usage (from app/backend/):

    conda run -n advandeb python scripts/gen_elicitation_types.py          # write
    conda run -n advandeb python scripts/gen_elicitation_types.py --check  # exit 1 if stale

`tests/test_elicitation_contract.py` runs the check, so a model change that is
not regenerated fails the backend suite, and a client that reads a field the
model does not have fails `vue-tsc`.

Enrolment is generated the same way for the same reason: its client sent
`full_name` and `consent_acknowledgement` to a model that asks for `name` and
`consent` (every signup a 422), and the admin view posted `{decision, ...}` to
a model that asks for `{approve, ...}`.
"""
from __future__ import annotations

import argparse
import json
import sys
import typing
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, List, Type

from pydantic import BaseModel

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.models import elicitation as m  # noqa: E402
from app.models import enrolment as en  # noqa: E402

TYPES_DIR = BACKEND.parent / "frontend" / "src" / "types"
OUT = TYPES_DIR / "elicitation.generated.ts"

# Literal aliases emitted by name, so an enum in a field reads `TaskType`
# rather than an anonymous union that silently stops matching when one changes.
ALIASES = [
    "TaskType", "PassageDirection", "EvidentialRole", "ProvenanceType",
    "ScopeVerdict", "AssessabilityVerdict", "EvidenceCondition",
    "ElicitationEventType", "GuidelineSection",
]

# What the server sends. Every field is present in the JSON (pydantic
# serialises defaults), so every field is required on the TypeScript side.
RESPONSES: List[Type[BaseModel]] = [
    m.EvidencePassage, m.QueueItem, m.DecisionReceipt, m.EventReceipt,
    m.ElicitationProgress, m.TaskOption, m.TaskGuideline, m.Guidelines,
    m.HistoryItem, m.HistoryResponse, m.CalibrationItem,
    m.CalibrationFeedback, m.CalibrationStatus, m.RecallSummary,
    m.PanelCoverage, m.ExpertStats, m.AwaitingCalibration, m.AdminStats,
    m.ExpertListEntry, m.ExpertList,
]

# What the client sends. A field with a default may be omitted.
REQUESTS: List[Type[BaseModel]] = [
    m.PassageJudgment, m.ElicitationDecision, m.CalibrationDecision,
    m.ElicitationEvent,
]


@dataclass(frozen=True)
class Target:
    """One generated file: a models module and what to export from it."""
    module: ModuleType
    out: Path
    aliases: List[str]
    responses: List[Type[BaseModel]]
    requests: List[Type[BaseModel]]


TARGETS: List[Target] = [
    Target(m, OUT, ALIASES, RESPONSES, REQUESTS),
    Target(
        en, TYPES_DIR / "enrolment.generated.ts",
        ["Tier", "RequestStatus"],
        [en.EnrolmentSubmitted, en.EnrolmentRequestRecord,
         en.EnrolmentRequestList, en.EnrolmentDecisionResult,
         en.StylizedFactCategory, en.CategoryList],
        [en.EnrolmentRequest, en.EnrolmentDecision],
    ),
]


def _alias_sets(module: ModuleType = m,
                aliases: List[str] = ALIASES) -> Dict[frozenset, str]:
    return {frozenset(typing.get_args(getattr(module, a))): a for a in aliases}


def _ts(schema: Dict[str, Any], aliases: Dict[frozenset, str]) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if "allOf" in schema and len(schema["allOf"]) == 1:
        return _ts(schema["allOf"][0], aliases)
    if "anyOf" in schema:
        parts: List[str] = []
        for s in schema["anyOf"]:
            t = _ts(s, aliases)
            if t not in parts:
                parts.append(t)
        # `Optional[Any]` is just `unknown`; `unknown | null` says nothing more.
        return "unknown" if "unknown" in parts else " | ".join(parts)
    if "const" in schema:
        return json.dumps(schema["const"])
    if "enum" in schema:
        named = aliases.get(frozenset(schema["enum"]))
        return named or " | ".join(json.dumps(v) for v in schema["enum"])
    t = schema.get("type")
    if t == "string":
        return "string"
    if t in ("integer", "number"):
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "null":
        return "null"
    if t == "array":
        inner = _ts(schema.get("items") or {}, aliases)
        return f"({inner})[]" if "|" in inner else f"{inner}[]"
    if t == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict) and extra:
            return f"Record<string, {_ts(extra, aliases)}>"
        return "Record<string, unknown>"
    return "unknown"


def _doc(model: Type[BaseModel]) -> str:
    text = (model.__doc__ or "").strip().split("\n\n")[0]
    text = " ".join(line.strip() for line in text.splitlines())
    return f"/** {text} */\n" if text else ""


def _interface(model: Type[BaseModel], response: bool,
               aliases: Dict[frozenset, str]) -> str:
    schema = model.model_json_schema(
        mode="serialization" if response else "validation")
    required = set(schema.get("required") or [])
    lines = [f"{_doc(model)}export interface {model.__name__} {{"]
    for name, prop in (schema.get("properties") or {}).items():
        optional = "" if (response or name in required) else "?"
        lines.append(f"  {name}{optional}: {_ts(prop, aliases)}")
    lines.append("}")
    return "\n".join(lines)


def render(target: Target = None) -> str:
    target = target or TARGETS[0]
    aliases = _alias_sets(target.module, target.aliases)
    src = target.module.__name__.replace(".", "/")
    out = [
        f"// GENERATED from app/backend/{src}.py by",
        "// app/backend/scripts/gen_elicitation_types.py — do not edit by hand.",
        "// Regenerate after changing a model; the backend suite fails while",
        "// this file is stale (tests/test_elicitation_contract.py).",
        "/* eslint-disable */",
        "",
    ]
    for a in target.aliases:
        values = " | ".join(
            json.dumps(v) for v in typing.get_args(getattr(target.module, a)))
        out.append(f"export type {a} = {values}")
    out.append("")
    out.append("// ---- responses: every field is present ----")
    out.append("")
    for model in target.responses:
        out.append(_interface(model, True, aliases))
        out.append("")
    out.append("// ---- requests: fields with a server default may be omitted ----")
    out.append("")
    for model in target.requests:
        out.append(_interface(model, False, aliases))
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the committed file is stale; write nothing")
    args = ap.parse_args()
    stale = 0
    for target in TARGETS:
        text = render(target)
        current = target.out.read_text() if target.out.exists() else ""
        if args.check:
            if current != text:
                print(f"{target.out} is stale — run "
                      "scripts/gen_elicitation_types.py", file=sys.stderr)
                stale += 1
            continue
        target.out.write_text(text)
        print(f"wrote {target.out}")
    if args.check:
        print("up to date" if not stale else f"{stale} file(s) stale")
        return 1 if stale else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
