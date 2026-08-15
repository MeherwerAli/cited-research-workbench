import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from .answering import Answerer
from .models import ResearchRun, ResearchRunCreate
from .retrieval import Retriever
from .workflow import SQLiteWorkflowStore, WorkflowConflictError


class ApprovalExpiredError(WorkflowConflictError):
    pass


class ResearchService:
    def __init__(
        self,
        store: SQLiteWorkflowStore,
        retriever: Retriever,
        answerer: Answerer,
        approval_threshold_usd: Decimal,
        approval_ttl_seconds: int = 900,
    ) -> None:
        self.store = store
        self.retriever = retriever
        self.answerer = answerer
        self.approval_threshold_usd = approval_threshold_usd
        self.approval_ttl_seconds = approval_ttl_seconds

    def start(self, request: ResearchRunCreate, trace_id: str) -> ResearchRun:
        approval_required = (
            request.estimated_cost_usd > self.approval_threshold_usd
            or request.external_network
            or request.export_requested
        )
        now = datetime.now(UTC)
        run = ResearchRun(
            id=f"run_{uuid.uuid4().hex}",
            query=request.query,
            state="awaiting_approval" if approval_required else "draft",
            estimated_cost_usd=request.estimated_cost_usd,
            approval_required=approval_required,
            trace_id=trace_id,
            created_at=now,
            updated_at=now,
        )
        return self.store.create(
            run,
            "requester",
            {
                "estimated_cost_usd": str(request.estimated_cost_usd),
                "external_network": request.external_network,
                "export_requested": request.export_requested,
            },
        )

    def approve(self, run_id: str, actor: str, *, now: datetime | None = None) -> ResearchRun:
        current = self.store.get(run_id)
        approved_at = now or datetime.now(UTC)
        updated = current.model_copy(
            update={
                "state": "draft",
                "updated_at": approved_at,
                "approved_by": actor,
                "approval_expires_at": approved_at + timedelta(seconds=self.approval_ttl_seconds),
            }
        )
        return self.store.transition(
            run_id,
            {"awaiting_approval"},
            updated,
            "run.approved",
            actor,
            {"approved": True},
        )

    def cancel(self, run_id: str, actor: str) -> ResearchRun:
        current = self.store.get(run_id)
        updated = current.model_copy(update={"state": "cancelled", "updated_at": datetime.now(UTC)})
        return self.store.transition(
            run_id,
            {"draft", "awaiting_approval"},
            updated,
            "run.cancelled",
            actor,
            {"cancelled": True},
        )

    async def execute(self, run_id: str, *, now: datetime | None = None) -> ResearchRun:
        current = self.store.get(run_id)
        observed_at = now or datetime.now(UTC)
        if current.approval_required and (
            current.approval_expires_at is None or current.approval_expires_at <= observed_at
        ):
            expired = current.model_copy(
                update={
                    "state": "awaiting_approval",
                    "updated_at": observed_at,
                    "approved_by": None,
                    "approval_expires_at": None,
                }
            )
            self.store.transition(
                run_id,
                {"draft"},
                expired,
                "run.approval_expired",
                "system",
                {"expired": True},
            )
            raise ApprovalExpiredError("persisted approval expired before execution")
        executing = current.model_copy(update={"state": "executing", "updated_at": observed_at})
        self.store.transition(
            run_id, {"draft"}, executing, "run.executing", "system", {"query_hash_only": True}
        )
        try:
            hits = await self.retriever.search(current.query, limit=5)
            answer = await self.answerer.answer(current.query, hits, current.trace_id)
            completed = executing.model_copy(
                update={"state": "completed", "answer": answer, "updated_at": datetime.now(UTC)}
            )
            return self.store.transition(
                run_id,
                {"executing"},
                completed,
                "run.completed",
                "system",
                {"abstained": answer.abstained, "claim_count": len(answer.claims)},
            )
        except Exception as error:
            failed = executing.model_copy(
                update={"state": "failed", "updated_at": datetime.now(UTC)}
            )
            self.store.transition(
                run_id,
                {"executing"},
                failed,
                "run.failed",
                "system",
                {"error_type": error.__class__.__name__},
            )
            raise
