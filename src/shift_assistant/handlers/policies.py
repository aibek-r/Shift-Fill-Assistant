"""Answers from facility policies: the existing RAG search, then a keyword check, then the
section quoted as is with its citation. Nothing here is written by a model.

The search already drops excerpts below `retrieval_min_score`. On top of that, an excerpt only
counts when it shares a meaningful word with the question (a parking question needs a section
that mentions parking). This keeps "What's the dress code at Bayview?" from being answered with
the closest unrelated section; the answer is "I couldn't find this" instead of a guess.
"""

from __future__ import annotations

import re

from shift_assistant import templates
from shift_assistant.contracts import Answer, IntentEntities
from shift_assistant.handlers.common import HandlerReply, answered, find_facility, short_name
from shift_assistant.repository import StaffingRepository
from shift_assistant.retrieval.knowledge import GLOBAL_SCOPE
from shift_assistant.tools.schemas import (
    PolicyExcerpt,
    SearchFacilityPoliciesArgs,
    SearchFacilityPoliciesResult,
)
from shift_assistant.tools.toolkit import StaffingToolkit


def _word_set(text: str) -> frozenset[str]:
    return frozenset(text.split())


_TOP_K = 8  # the most the tool allows: a facility handbook plus the global policies
_GLOBAL_NAME = "staffing operations"
_STOPWORDS = _word_set(
    "a about after all an and any are as at be before but by can could do does for from get "
    "has have how i if in into is it its me my of on or our should so tell than that the "
    "their them there they this to us we what whats when where which who why will with "
    "would you your"
)
# Words every staffing question shares; they say nothing about which section answers it.
_GENERIC = _word_set(
    "nurse nurses rn rns clinician clinicians agency staff staffing shift shifts policy "
    "policies facility facilities hospital rule rules legal legally illegal allowed allow "
    "ok okay"
)
_SHORT_TERMS = frozenset({"icu", "ed", "er", "picu", "nicu", "ehr"})


class PolicyQuestions:
    def __init__(self, repository: StaffingRepository, toolkit: StaffingToolkit) -> None:
        self._repository = repository
        self._toolkit = toolkit

    def answer(self, text: str, entities: IntentEntities) -> HandlerReply:
        match = find_facility(text, entities, self._repository)
        if match.unknown_name:
            known = [f.name for f in self._repository.facilities()]
            return answered(templates.facility_not_found(match.unknown_name, known))
        facilities = [match.facility] if match.facility else self._repository.facilities()
        not_found = templates.policy_not_found(
            short_name(match.facility.name) if match.facility else "facility"
        )

        terms = self._terms(text)
        excerpts = self._search([f.id for f in facilities], text)
        scored = [
            (score, rank, e) for rank, e in enumerate(excerpts) if (score := _score(terms, e))[0]
        ]
        if not terms or not scored:
            return answered(not_found, Answer())
        _, _, best = max(scored, key=lambda item: (item[0], -item[1]))
        if best.facility_id == GLOBAL_SCOPE:
            scope = _GLOBAL_NAME
        else:
            facility = self._repository.facility(best.facility_id)
            scope = facility.name if facility else best.facility_id
        return answered(
            templates.policy_found(scope, best.section),
            Answer(citations=[best], sources=[best.chunk_id]),
        )

    def _search(self, facility_ids: list[str], text: str) -> list[PolicyExcerpt]:
        query = text.strip()[:300]
        if len(query) < 3:
            return []
        seen: dict[str, PolicyExcerpt] = {}
        for facility_id in facility_ids:
            args = SearchFacilityPoliciesArgs(facility_id=facility_id, query=query, top_k=_TOP_K)
            result = self._toolkit.search_facility_policies(args).result
            assert isinstance(result, SearchFacilityPoliciesResult)
            for excerpt in result.excerpts:
                seen.setdefault(excerpt.chunk_id, excerpt)
        return list(seen.values())

    def _terms(self, text: str) -> set[str]:
        """Meaningful words of the question: no stopwords, generic words or facility names."""
        names = {w for f in self._repository.facilities() for w in _words(f.name)}
        return {
            w
            for w in _words(text)
            if w not in _STOPWORDS
            and w not in _GENERIC
            and w not in names
            and (len(w) >= 3 or w in _SHORT_TERMS)
            and not w.isdigit()
        }


def _words(text: str) -> list[str]:
    plain = text.lower().replace("'", "").replace("\N{RIGHT SINGLE QUOTATION MARK}", "")
    return re.findall(r"[a-z0-9]+", plain)


def _score(terms: set[str], excerpt: PolicyExcerpt) -> tuple[int, int]:
    """(distinct question words found, total matches) in the section title and text."""
    words = _words(f"{excerpt.section} {excerpt.text}")
    hits = [term for term in terms for word in words if _same_word(term, word)]
    return (len(set(hits)), len(hits)) if hits else (0, 0)


def _same_word(term: str, word: str) -> bool:
    """'park' matches 'parking'; 'arrive' matches 'arrival'; 'cancel' matches 'cancellation'."""
    if term == word:
        return True
    if len(term) >= 4 and word.startswith(term):
        return True
    return len(term) >= 5 and len(word) >= 5 and term[:5] == word[:5]
