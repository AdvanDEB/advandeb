"""The generated TypeScript types match the pydantic models.

No database. Fails when a model changes and
`scripts/gen_elicitation_types.py` was not re-run — the moment the client and
server would otherwise start to disagree, silently, as they did three ways at
once before the types were generated.
"""
from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

from app.models import elicitation as m
from app.models import enrolment as en

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_elicitation_types.py"


def _gen():
    if "gen_elicitation_types" in sys.modules:
        return sys.modules["gen_elicitation_types"]
    spec = importlib.util.spec_from_file_location("gen_elicitation_types", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Registered before execution: the script's dataclass resolves its own
    # module through sys.modules.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_generated_types_are_up_to_date():
    gen = _gen()
    for target in gen.TARGETS:
        assert target.out.exists(), f"{target.out} missing — run {SCRIPT.name}"
        assert target.out.read_text() == gen.render(target), (
            f"{target.out.name} is stale — run scripts/{SCRIPT.name}")


def _ts_fields(text: str, name: str) -> set:
    block = re.search(rf"export interface {name} \{{(.*?)\n\}}", text, re.S)
    assert block, name
    return {re.match(r"\s*(\w+)\??:", line).group(1)
            for line in block.group(1).strip().splitlines()}


def test_every_exported_interface_has_exactly_the_model_fields():
    gen = _gen()
    for target in gen.TARGETS:
        text = target.out.read_text()
        for model in target.responses + target.requests:
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


def _enrolment_ts() -> str:
    gen = _gen()
    return next(t for t in gen.TARGETS if t.module is en).out.read_text()


def test_enrolment_request_declares_what_the_server_requires():
    """The signup form sent `full_name` and `consent_acknowledgement`; the
    model asks for `name` and `consent`. Every signup was a 422."""
    fields = _ts_fields(_enrolment_ts(), "EnrolmentRequest")
    assert {"name", "consent"} <= fields
    assert not {"full_name", "consent_acknowledgement"} & fields


def test_enrolment_decision_is_approve_not_decision():
    """The admin view posted `{decision: 'approve'}`; the model asks for
    `{approve: true}`."""
    assert _ts_fields(_enrolment_ts(), "EnrolmentDecision") == {
        "approve", "tier", "note"}


def test_request_records_are_served_with_id():
    """Served as `_id` while the admin view read `id`, every decision went to
    /requests/undefined/decide."""
    assert "id" in _ts_fields(_enrolment_ts(), "EnrolmentRequestRecord")
    rec = en.EnrolmentRequestRecord.model_validate({
        "_id": "abc", "name": "n", "email": "a@b.org",
        "created_at": "2026-10-28T00:00:00Z"})
    assert rec.model_dump(by_alias=True)["id"] == "abc"


def test_every_evidence_block_category_has_a_label():
    """The evidence block (facts 1201-1262) spans these five categories; the
    signup form must offer each under a real label, not a derived one."""
    for k in ("core_deb_rules", "hypoxia_dissolved_oxygen",
              "phytoplankton_chlorophyll", "phytoplankton_eps",
              "phytoplankton_nc_ratio"):
        assert k in en.CATEGORY_LABELS
    assert "currently_assessed" in _ts_fields(_enrolment_ts(), "StylizedFactCategory")
