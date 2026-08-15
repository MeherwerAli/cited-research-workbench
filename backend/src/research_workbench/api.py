import asyncio
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .answering import DeterministicCitedAnswerer, GatewayCitedAnswerer
from .config import Settings
from .models import (
    ApprovalRequest,
    AuditEvent,
    DocumentRecord,
    ResearchRun,
    ResearchRunCreate,
)
from .pdf_ingest import PDFValidationError, ingest_pdf
from .retrieval import HTTPReranker, InMemoryHybridRetriever, QdrantHybridRetriever, Retriever
from .service import ResearchService
from .workflow import SQLiteWorkflowStore, WorkflowConflictError


def create_app(
    settings: Settings | None = None,
    *,
    retriever: Retriever | None = None,
    workflow_store: SQLiteWorkflowStore | None = None,
) -> FastAPI:
    settings = settings or Settings()
    if workflow_store is None:
        database = Path(settings.database_path)
        database.parent.mkdir(parents=True, exist_ok=True)
        workflow_store = SQLiteWorkflowStore(str(database))
    retriever = retriever or (
        QdrantHybridRetriever(
            settings.qdrant_url,
            reranker=HTTPReranker(settings.reranker_url) if settings.reranker_url else None,
        )
        if settings.qdrant_url
        else InMemoryHybridRetriever()
    )
    answerer = (
        GatewayCitedAnswerer(settings.gateway_url, settings.gateway_api_key)
        if settings.gateway_url and settings.gateway_api_key
        else DeterministicCitedAnswerer()
    )
    service = ResearchService(
        workflow_store,
        retriever,
        answerer,
        settings.approval_threshold_usd,
        settings.approval_ttl_seconds,
    )
    documents: dict[str, DocumentRecord] = {}
    app = FastAPI(
        title="Cited Research Workbench",
        version="0.1.0",
        description="Page-cited PDF research with persisted approvals and audit events.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3100", "http://localhost:3000"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    app.state.research_service = service
    app.state.workflow_store = workflow_store
    app.state.retriever = retriever

    @app.middleware("http")
    async def add_trace_id(request: Request, call_next):  # type: ignore[no-untyped-def]
        trace_id = request.headers.get("X-Trace-Id") or uuid.uuid4().hex
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.exception_handler(WorkflowConflictError)
    async def conflict(_: Request, error: WorkflowConflictError):  # type: ignore[no-untyped-def]
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=409, content={"code": "workflow_conflict", "message": str(error)}
        )

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/documents", response_model=DocumentRecord, status_code=201)
    async def upload_document(
        file: Annotated[UploadFile, File(description="Digital-text PDF, max 25 MB and 200 pages")],
    ) -> DocumentRecord:
        data = await file.read(settings.max_pdf_bytes + 1)
        try:
            ingested = ingest_pdf(
                data,
                file.filename or "document.pdf",
                max_bytes=settings.max_pdf_bytes,
                max_pages=settings.max_pdf_pages,
            )
        except PDFValidationError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        await retriever.index(ingested.chunks)
        documents[ingested.record.id] = ingested.record
        return ingested.record

    @app.get("/v1/documents/{document_id}", response_model=DocumentRecord)
    async def document(document_id: str) -> DocumentRecord:
        try:
            return documents[document_id]
        except KeyError as error:
            raise HTTPException(status_code=404, detail="document not found") from error

    @app.post("/v1/research-runs", response_model=ResearchRun, status_code=201)
    async def start_run(
        payload: ResearchRunCreate,
        request: Request,
        background: BackgroundTasks,
    ) -> ResearchRun:
        run = service.start(payload, request.state.trace_id)
        if not run.approval_required:
            background.add_task(service.execute, run.id)
        return run

    @app.get("/v1/research-runs/{run_id}", response_model=ResearchRun)
    async def get_run(run_id: str) -> ResearchRun:
        try:
            return workflow_store.get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.post("/v1/research-runs/{run_id}/approvals", response_model=ResearchRun)
    async def approve_run(
        run_id: str, payload: ApprovalRequest, background: BackgroundTasks
    ) -> ResearchRun:
        try:
            approved = service.approve(run_id, payload.actor)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        background.add_task(service.execute, run_id)
        return approved

    @app.post("/v1/research-runs/{run_id}/cancel", response_model=ResearchRun)
    async def cancel_run(run_id: str, payload: ApprovalRequest) -> ResearchRun:
        try:
            return service.cancel(run_id, payload.actor)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error

    @app.get("/v1/research-runs/{run_id}/audit", response_model=list[AuditEvent])
    async def audit(run_id: str) -> list[AuditEvent]:
        try:
            workflow_store.get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        return workflow_store.events(run_id)

    @app.get("/v1/research-runs/{run_id}/events")
    async def events(
        run_id: str,
        last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
    ) -> StreamingResponse:
        try:
            workflow_store.get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="run not found") from error
        after = int(last_event_id or "0")

        async def stream() -> AsyncIterator[str]:
            cursor = after
            idle_rounds = 0
            while idle_rounds < 3:
                current = workflow_store.events(run_id, cursor)
                if current:
                    idle_rounds = 0
                    for event in current:
                        cursor = event.id
                        yield f"id: {event.id}\nevent: audit\ndata: {event.model_dump_json()}\n\n"
                else:
                    idle_rounds += 1
                    yield ": heartbeat\n\n"
                run = workflow_store.get(run_id)
                if run.state in {"completed", "failed", "cancelled"} and not current:
                    break
                await asyncio.sleep(0.05)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
        )

    return app
