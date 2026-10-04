from __future__ import annotations

import json

from pydantic import BaseModel

from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.evidence import EvidenceLedger
from shift_assistant.tools.registry import ToolRegistry, ToolSpec, build_tool_registry
from shift_assistant.tools.toolkit import StaffingToolkit, ToolOutput


def test_unknown_facility_error_lists_known_facilities(registry: ToolRegistry) -> None:
    result = registry.execute("find_open_shifts", {"facility": "Mercy General"})

    assert not result.ok
    assert "No facility matches 'Mercy General'" in result.content
    assert "St. Mary's Medical Center (FAC-001)" in result.content


def test_facility_names_match_loosely(registry: ToolRegistry) -> None:
    result = registry.execute("find_open_shifts", {"facility": "st marys", "unit": "ICU"})

    assert result.ok
    assert set(result.evidence.shifts) == {"SHF-1001", "SHF-1003"}


def test_invalid_arguments_are_explained_not_raised(registry: ToolRegistry) -> None:
    result = registry.execute("evaluate_candidates", {"shift_id": "SHF-1001", "clinician_ids": []})

    assert not result.ok
    assert result.content.startswith("ERROR: Invalid arguments for evaluate_candidates")
    assert "clinician_ids" in result.content


def test_unknown_tool_is_reported(registry: ToolRegistry) -> None:
    result = registry.execute("delete_database", {})

    assert not result.ok
    assert "Unknown tool" in result.content


def test_clinician_search_exposes_no_contact_details(
    registry: ToolRegistry, repository: StaffingRepository
) -> None:
    result = registry.execute("search_clinicians", {"shift_id": "SHF-1001", "query": "nights"})

    assert result.ok
    for clinician in repository.clinicians():
        assert clinician.email not in result.content
        assert clinician.phone not in result.content
        for credential in clinician.credentials:
            assert credential.number is None or credential.number not in result.content


def test_evaluation_reports_unknown_ids_separately(registry: ToolRegistry) -> None:
    result = registry.execute(
        "evaluate_candidates", {"shift_id": "SHF-1001", "clinician_ids": ["C-101", "C-999"]}
    )
    payload = json.loads(result.content)

    assert payload["unknown_clinician_ids"] == ["C-999"]
    assert [e["clinician_id"] for e in payload["evaluations"]] == ["C-101"]


def test_pool_and_credential_checks_are_evidence_not_model_context(
    registry: ToolRegistry,
) -> None:
    search = registry.execute("search_clinicians", {"shift_id": "SHF-1001", "limit": 2})
    evaluation = registry.execute(
        "evaluate_candidates", {"shift_id": "SHF-1001", "clinician_ids": ["C-101"]}
    )

    assert len(search.evidence.candidate_pools["SHF-1001"]) == 9  # whole pool, not just top 2
    assert "credentials" not in json.loads(evaluation.content)["evaluations"][0]
    assert evaluation.evidence.evaluations["SHF-1001/C-101"].credentials


def test_outreach_is_refused_for_ineligible_clinicians(registry: ToolRegistry) -> None:
    result = registry.execute(
        "draft_outreach",
        {
            "shift_id": "SHF-1001",
            "clinician_id": "C-102",
            "personal_note": "Your ICU experience is a great fit for this shift.",
        },
    )

    assert not result.ok
    assert "not eligible" in result.content
    assert result.evidence.drafts == {}


def test_outreach_rejects_pay_rates_in_the_note(registry: ToolRegistry) -> None:
    result = registry.execute(
        "draft_outreach",
        {
            "shift_id": "SHF-1001",
            "clinician_id": "C-101",
            "personal_note": "This night shift pays $95 per hour, a great fit for you.",
        },
    )

    assert not result.ok
    assert "pay rates" in result.content


def test_outreach_facts_come_from_the_system_of_record(registry: ToolRegistry) -> None:
    result = registry.execute(
        "draft_outreach",
        {
            "shift_id": "SHF-1001",
            "clinician_id": "C-104",
            "personal_note": "We would love to have you on this shift.",
        },
    )
    draft = result.evidence.drafts["DRAFT-SHF-1001-C-104"]

    assert draft.body.startswith("Hi Daniel,")
    assert "St. Mary's Medical Center (Austin, TX)" in draft.body
    assert "Wed, Oct 14, 2026, 7:00 PM to Thu, Oct 15, 2026, 7:00 AM" in draft.body
    assert "Your ACLS expires soon" in draft.body  # deterministic credential reminder
    assert "Please reply by Mon, Oct 12, 2026, 7:00 PM" in draft.body


class _Args(BaseModel):
    text: str


def test_unexpected_tool_failures_are_contained() -> None:
    def explode(_: _Args) -> ToolOutput:
        raise RuntimeError("database connection string leaked here")

    registry = ToolRegistry([ToolSpec("explode", "boom", _Args, explode)], output_char_limit=1000)
    result = registry.execute("explode", {"text": "hi"})

    assert not result.ok
    assert "failed unexpectedly" in result.content
    assert "leaked" not in result.content


def test_long_outputs_are_truncated() -> None:
    class _Big(BaseModel):
        text: str

    registry = ToolRegistry(
        [
            ToolSpec(
                "big",
                "big",
                _Args,
                lambda a: ToolOutput(_Big(text=a.text * 1000), EvidenceLedger()),
            )
        ],
        output_char_limit=500,
    )
    result = registry.execute("big", {"text": "abc"})
    payload = json.loads(result.content)  # still valid JSON

    assert result.ok
    assert len(result.content) <= 500
    assert payload["text"].endswith("...")
    assert "shortened" in payload["truncated"]


def test_long_lists_are_trimmed_by_whole_items(
    toolkit: StaffingToolkit, repository: StaffingRepository
) -> None:
    registry = build_tool_registry(toolkit, output_char_limit=2000)
    all_ids = [c.id for c in repository.clinicians()]

    result = registry.execute(
        "evaluate_candidates", {"shift_id": "SHF-1001", "clinician_ids": all_ids}
    )
    payload = json.loads(result.content)

    assert len(result.content) <= 2000
    shown = len(payload["evaluations"])
    assert 0 < shown < len(all_ids)
    assert payload["truncated"].startswith(f"{len(all_ids) - shown} evaluations item(s) omitted")
    assert len(result.evidence.evaluations) == len(all_ids)  # the ledger keeps everything
