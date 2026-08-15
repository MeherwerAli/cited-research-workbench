from decimal import Decimal

import httpx
import pytest

from research_workbench.api import create_app
from research_workbench.config import Settings
from research_workbench.retrieval import InMemoryHybridRetriever
from research_workbench.workflow import SQLiteWorkflowStore


@pytest.mark.asyncio
async def test_run_api_exposes_resumable_audit_events(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = SQLiteWorkflowStore(str(tmp_path / "api.db"))
    app = create_app(
        Settings(database_path=str(tmp_path / "unused.db"), approval_threshold_usd=Decimal("0.10")),
        retriever=InMemoryHybridRetriever(),
        workflow_store=store,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post(
            "/v1/research-runs",
            json={"query": "Question that has no indexed support", "estimated_cost_usd": "0"},
        )
        assert created.status_code == 201
        run_id = created.json()["id"]
        current = await client.get(f"/v1/research-runs/{run_id}")
        assert current.json()["state"] == "completed"
        audit = await client.get(f"/v1/research-runs/{run_id}/audit")
        assert len(audit.json()) == 3
        events = await client.get(
            f"/v1/research-runs/{run_id}/events", headers={"Last-Event-ID": "1"}
        )
        assert "id: 2" in events.text
        assert "id: 1" not in events.text
