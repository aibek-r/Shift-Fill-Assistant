from __future__ import annotations

from shift_assistant.retrieval.embedder import HashingEmbedder
from shift_assistant.retrieval.knowledge import GLOBAL_SCOPE, chunk_policy_markdown
from shift_assistant.retrieval.vector_index import Document, VectorIndex
from shift_assistant.tools.schemas import SearchFacilityPoliciesArgs, SearchFacilityPoliciesResult
from shift_assistant.tools.toolkit import StaffingToolkit

HANDBOOK = """# Handbook

## Parking and arrival
Park in Garage C.

## Empty section

## ICU unit profile
CCRN is preferred.
"""


def test_chunking_produces_one_citable_chunk_per_section() -> None:
    chunks = chunk_policy_markdown("FAC-009", HANDBOOK)

    assert [c.id for c in chunks] == ["FAC-009#parking-and-arrival", "FAC-009#icu-unit-profile"]
    assert chunks[1].metadata == {"facility_id": "FAC-009", "section": "ICU unit profile"}
    assert chunks[1].text.startswith("ICU unit profile\n")


def test_vector_index_ranks_by_similarity_and_applies_filters() -> None:
    index = VectorIndex(
        HashingEmbedder(),
        [
            Document("a", "night shift parking garage"),
            Document("b", "pediatric ventilator experience"),
            Document("c", "night shift huddle"),
        ],
    )

    assert [h.document.id for h in index.search("night shift parking", top_k=2)] == ["a", "c"]
    only_b = index.search("night shift", where=lambda d: d.id == "b")
    assert [h.document.id for h in only_b] == ["b"]  # filter applies before ranking
    assert index.search("night shift parking", min_score=0.99) == []


def test_policy_search_never_leaks_other_facilities(toolkit: StaffingToolkit) -> None:
    output = toolkit.search_facility_policies(
        SearchFacilityPoliciesArgs(facility_id="FAC-001", query="unit profile parking", top_k=8)
    )
    assert isinstance(output.result, SearchFacilityPoliciesResult)

    scopes = {e.facility_id for e in output.result.excerpts}
    assert scopes <= {"FAC-001", GLOBAL_SCOPE}
    assert set(output.evidence.policy_excerpts) == {e.chunk_id for e in output.result.excerpts}
