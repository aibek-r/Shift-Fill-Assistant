"""Input guard: the first step for every coordinator message, before routing or any AI.

It normalizes the text so every later step reads the same characters: Unicode compatibility
forms are folded (full-width letters and digits become plain ones), Windows line endings become
newlines, and control, zero-width and text-direction characters are removed, because they can
hide text from a human reader while a model still reads it.

Length is limited by the request contract (`MAX_MESSAGE_CHARS`). Blocking checks (prompt
injection, personal data, abuse and rate limits) are planned for a later phase and will return
`GuardVerdict.BLOCK` from here.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

# C0 and C1 controls except tab and newline, zero-width characters, and bidirectional overrides.
_HIDDEN_CHARACTERS = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]"
)


class GuardVerdict(StrEnum):
    ALLOW = "allow"
    BLOCK = "block"


class GuardResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: GuardVerdict
    text: str  # normalized text; later steps read only this
    findings: tuple[str, ...] = ()  # machine-readable codes, never the message text


class InputGuard:
    def check(self, text: str) -> GuardResult:
        normalized = unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")
        cleaned = _HIDDEN_CHARACTERS.sub("", normalized).strip()
        findings = ("hidden_characters_removed",) if cleaned != normalized.strip() else ()
        return GuardResult(verdict=GuardVerdict.ALLOW, text=cleaned, findings=findings)
