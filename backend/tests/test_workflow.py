from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from research_workbench.answering import DeterministicCitedAnswerer
from research_workbench.models import Chunk, ResearchRunCreate
from research_workbench.retrieval import InMemoryHybridRetriever
from research_workbench.service import ApprovalExpiredError, ResearchService
from research_workbench.workflow import SQLiteWorkflowStore, WorkflowConflictError


@pytest.fixture
def store(tmp_path):  # type: ignore[no-untyped-def]
    return SQLiteWorkflowStore(str(tmp_path / "runs.db"))


@pytest.fixture
async def service(store: SQLiteWorkflowStore) -> ResearchService:
    retriever = InMemoryHybridRetriever()
    await retriever.index(
        [
            Chunk(
                id="chk_1",
                document_id="doc_1",
                page=3,
                text="Approval is mandatory before an expensive action executes.",
                source_sha256="a" * 64,
            )
        ]
    )
    return ResearchService(
        store,
        retriever,
        DeterministicCitedAnswerer(),
        approval_threshold_usd=Decimal("0.10"),
    )


@pytest.mark.asyncio
async def test_expensive_action_cannot_execute_without_persisted_approval(
    service: ResearchService,
) -> None:
    run = service.start(
        ResearchRunCreate(query="Why is approval mandatory?", estimated_cost_usd=Decimal("0.11")),
        "trace",
    )
    assert run.state == "awaiting_approval"
    with pytest.raises(WorkflowConflictError):
        await service.execute(run.id)
    approved = service.approve(run.id, "reviewer")
    assert approved.state == "draft"
    completed = await service.execute(run.id)
    assert completed.state == "completed"
    assert completed.answer and completed.answer.claims[0].citations[0].page == 3


@pytest.mark.asyncio
async def test_duplicate_approval_and_replay_are_rejected(service: ResearchService) -> None:
    run = service.start(
        ResearchRunCreate(query="Approve network access", external_network=True), "trace"
    )
    service.approve(run.id, "reviewer")
    with pytest.raises(WorkflowConflictError):
        service.approve(run.id, "reviewer")


@pytest.mark.asyncio
async def test_expired_approval_returns_to_approval_gate(service: ResearchService) -> None:
    run = service.start(
        ResearchRunCreate(query="Approve an external lookup", external_network=True), "trace"
    )
    approved_at = datetime.now(UTC)
    service.approve(run.id, "reviewer", now=approved_at)
    with pytest.raises(ApprovalExpiredError, match="expired"):
        await service.execute(run.id, now=approved_at + timedelta(seconds=901))
    current = service.store.get(run.id)
    assert current.state == "awaiting_approval"
    assert current.approved_by is None
    assert [event.event_type for event in service.store.events(run.id)][-1] == (
        "run.approval_expired"
    )


@pytest.mark.asyncio
async def test_audit_is_append_only_and_contains_hashes_not_raw_query(
    service: ResearchService, store: SQLiteWorkflowStore
) -> None:
    secret_query = "Explain approval without storing this raw sentence in the audit event"
    run = service.start(ResearchRunCreate(query=secret_query), "trace")
    await service.execute(run.id)
    events = store.events(run.id)
    assert [event.event_type for event in events] == [
        "run.created",
        "run.executing",
        "run.completed",
    ]
    assert all(len(event.detail_hash) == 64 for event in events)
    assert secret_query not in " ".join(event.model_dump_json() for event in events)
