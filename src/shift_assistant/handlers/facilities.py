"""Answers about facilities, built from facilities.json through the read-only get_facility_info
tool. Nothing here is written by a model."""

from __future__ import annotations

import re

from shift_assistant import templates
from shift_assistant.contracts import Answer, AnswerTable, IntentEntities, ResponseKind
from shift_assistant.handlers.common import HandlerReply, answered, find_facility
from shift_assistant.intent import requested_units
from shift_assistant.repository import StaffingRepository
from shift_assistant.tools.outreach import unit_label
from shift_assistant.tools.schemas import FacilityInfo, GetFacilityInfoArgs
from shift_assistant.tools.toolkit import StaffingToolkit

_I = re.IGNORECASE
_COMPACT = re.compile(r"\bcompact\b", _I)
_REST = re.compile(r"\brest\b", _I)
_REQUIREMENTS = re.compile(
    r"\b(?:credentials?|certifications?|certs?|licen[cs]es?|requirements?|qualifications?"
    r"|requires?|required|needs?)\b",
    _I,
)
_UNITS = re.compile(r"\bunits?\b", _I)


class FacilityQuestions:
    def __init__(self, repository: StaffingRepository, toolkit: StaffingToolkit) -> None:
        self._repository = repository
        self._toolkit = toolkit

    def answer(self, text: str, entities: IntentEntities) -> HandlerReply:
        match = find_facility(text, entities, self._repository)
        known = [f.name for f in self._repository.facilities()]
        if match.unknown_name:
            return answered(templates.facility_not_found(match.unknown_name, known))
        if match.facility is None:
            return HandlerReply(ResponseKind.CLARIFICATION, templates.which_facility(known))

        result = self._toolkit.get_facility_info(GetFacilityInfoArgs(facility=match.facility.id))
        info = result.result
        assert isinstance(info, FacilityInfo)
        units = [u.unit for u in info.units]
        asked_units = set(requested_units(text)) or ({entities.unit} if entities.unit else set())
        sources = [info.facility_id]

        if _COMPACT.search(text):
            message = templates.compact_license(info.name, info.accepts_compact_license, info.state)
            return answered(message, Answer(sources=sources))
        if _REST.search(text):
            return answered(
                templates.rest_hours(info.name, info.min_rest_hours), Answer(sources=sources)
            )
        if _REQUIREMENTS.search(text):
            if len(asked_units) == 1:
                unit = asked_units.pop()
                requirement = next((u for u in info.units if u.unit is unit), None)
                if requirement is None:
                    message = templates.unit_not_at_facility(info.name, unit, units)
                    return answered(message, Answer(sources=sources))
                message = templates.unit_requirements(
                    info.name,
                    unit,
                    requirement.required_credentials,
                    requirement.min_years_experience,
                )
                return answered(message, Answer(sources=sources))
            table = AnswerTable(
                columns=list(templates.REQUIREMENT_COLUMNS),
                rows=[
                    [
                        unit_label(u.unit),
                        templates.credential_list(u.required_credentials),
                        f"{u.min_years_experience} years",
                    ]
                    for u in info.units
                ],
            )
            return answered(
                templates.requirements_by_unit(info.name), Answer(table=table, sources=sources)
            )
        if _UNITS.search(text):
            return answered(templates.facility_units(info.name, units), Answer(sources=sources))
        return answered(
            templates.facility_overview(info.name, info.city, info.state, info.timezone),
            Answer(
                items=templates.overview_items(
                    units, info.accepts_compact_license, info.min_rest_hours
                ),
                sources=sources,
            ),
        )
