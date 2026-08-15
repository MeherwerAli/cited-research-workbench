from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DocumentRecord(BaseModel):
    id: str
    filename: str
    source_sha256: str
    page_count: int
    chunk_count: int
    state: Literal["indexed"] = "indexed"


class Chunk(BaseModel):
    id: str
    document_id: str
    page: int = Field(ge=1)
    text: str = Field(min_length=1)
    source_sha256: str


class SearchHit(BaseModel):
    chunk: Chunk
    dense_rank: int | None = None
    sparse_rank: int | None = None
    fused_score: float
    rerank_score: float


class Citation(BaseModel):
    document_id: str
    page: int = Field(ge=1)
    chunk_id: str


class CitedClaim(BaseModel):
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(min_length=1)


class CitedAnswer(BaseModel):
    answer: str
    claims: list[CitedClaim]
    abstained: bool

    @model_validator(mode="after")
    def citations_required_unless_abstaining(self) -> "CitedAnswer":
        if not self.abstained and (
            not self.claims or any(not claim.citations for claim in self.claims)
        ):
            raise ValueError("every non-abstaining claim requires a citation")
        if self.abstained and self.claims:
            raise ValueError("abstaining answers cannot contain claims")
        return self


RunState = Literal["draft", "awaiting_approval", "executing", "completed", "failed", "cancelled"]


class ResearchRunCreate(BaseModel):
    query: str = Field(min_length=3, max_length=4_000)
    estimated_cost_usd: Decimal = Field(default=Decimal("0"), ge=0)
    external_network: bool = False
    export_requested: bool = False


class ResearchRun(BaseModel):
    id: str
    query: str
    state: RunState
    estimated_cost_usd: Decimal
    approval_required: bool
    trace_id: str
    created_at: datetime
    updated_at: datetime
    approved_by: str | None = None
    approval_expires_at: datetime | None = None
    answer: CitedAnswer | None = None


class ApprovalRequest(BaseModel):
    actor: str = Field(min_length=2, max_length=100)


class AuditEvent(BaseModel):
    id: int
    run_id: str
    event_type: str
    actor: str
    state: RunState
    detail_hash: str
    trace_id: str
    created_at: datetime
