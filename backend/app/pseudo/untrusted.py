"""The request model of the safety check (ADR 0015 point 4).

Everything here is untrusted browser input. The model is strict and frozen; the clause
caps are checked by ``safety_pass`` so they give ``too_much_text``, not ``invalid_request``.
A list of acknowledged spans above ``MAX_ACKNOWLEDGED`` fails validation (``invalid_request``).
"""

from __future__ import annotations

from typing import Annotated, Final, Self

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, model_validator

MAX_CLAUSE_CHARS: Final = 40_000
MAX_DOCUMENT_CHARS: Final = 2_000_000
MAX_CLAUSES: Final = 2_000
MAX_ACKNOWLEDGED: Final = 50_000

ClauseId = Annotated[str, Field(pattern=r"^c[1-9][0-9]{0,3}$")]


class _Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)


class MaskedClause(_Strict):
    id: ClauseId
    text: str


class UntrustedMaskedDocument(_Strict):
    label: Annotated[str, Field(pattern=r"^[A-Z]$")]
    detector_version: str
    clauses: Annotated[list[MaskedClause], Field(min_length=1)]
    acknowledged_unmasked: Annotated[
        list[tuple[ClauseId, NonNegativeInt, NonNegativeInt]], Field(max_length=MAX_ACKNOWLEDGED)
    ]

    @model_validator(mode="after")
    def _valid(self) -> Self:
        ids = [clause.id for clause in self.clauses]
        if len(set(ids)) != len(ids):
            msg = "duplicate clause id"
            raise ValueError(msg)
        return self
