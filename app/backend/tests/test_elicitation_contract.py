"""The generated TypeScript types match the pydantic models.

No database. Fails when a model changes and
`scripts/gen_elicitation_types.py` was not re-run — the moment the client and
server would otherwise start to disagree, silently, as they did three ways at
once before the types were generated.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from app.models import elicitation as m

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_elicitation_types.py"


def _gen():
    spec = importlib.util.spec_from_file_location("gen_elicitation_types", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generated_types_are_up_to_date():
    gen = _gen()
    assert gen.OUT.exists(), f"{gen.OUT} missing — run {SCRIPT.name}"
    assert gen.OUT.read_text() == gen.render(), (
        f"{gen.OUT.name} is stale — run scripts/{SCRIPT.name}")


def _ts_fields(text: str, name: str) -> set:
    block = re.search(rf"export interface {name} \{{(.*?)\n\}}", text, re.S)
    assert block, name
    return {re.match(r"\s*(\w+)\??:", line).group(1)
            for line in block.group(1).strip().splitlines()}


def test_every_exported_interface_has_exactly_the_model_fields():
    gen = _gen()
    text = gen.OUT.read_text()
    for model in gen.RESPONSES + gen.REQUESTS:
        assert _ts_fields(text, model.__name__) == set(model.model_fields), model


def test_task_type_includes_the_evidence_task():
    """The specific drift that hid the evidence task from experts."""
    text = _gen().OUT.read_text()
    assert '"evidence"' in re.search(r"export type TaskType = (.*)", text).group(1)


def test_calibration_status_declares_what_the_client_gates_on():
    text = _gen().OUT.read_text()
    assert _ts_fields(text, "CalibrationStatus") == {
        "total", "completed", "correct", "done", "available"}
    assert set(m.CalibrationStatus.model_fields) == {
        "total", "completed", "correct", "done", "available"}
