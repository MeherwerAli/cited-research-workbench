import os
import uuid

import httpx
import pytest

from research_workbench.models import Chunk
from research_workbench.retrieval import QdrantHybridRetriever

QDRANT_URL = os.getenv("WORKBENCH_INTEGRATION_QDRANT_URL")
pytestmark = pytest.mark.skipif(
    not QDRANT_URL,
    reason="set a disposable Qdrant integration URL",
)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_qdrant_dense_sparse_rrf_preserves_page_payload() -> None:
    assert QDRANT_URL is not None
    collection = f"integration-{uuid.uuid4().hex}"
    retriever = QdrantHybridRetriever(QDRANT_URL, collection=collection)
    chunks = [
        Chunk(
            id=f"chk_{uuid.uuid4().hex}",
            document_id="doc_retry",
            page=1,
            text="Bounded retries use exponential backoff and random jitter.",
            source_sha256="a" * 64,
        ),
        Chunk(
            id=f"chk_{uuid.uuid4().hex}",
            document_id="doc_budget",
            page=2,
            text="Budget reservations prevent concurrent spend oversubscription.",
            source_sha256="b" * 64,
        ),
    ]
    try:
        await retriever.index(chunks)
        hits = await retriever.search("How does budget reservation stop oversubscription?")
        assert hits[0].chunk.document_id == "doc_budget"
        assert hits[0].chunk.page == 2
        assert hits[0].fused_score > 0
    finally:
        async with httpx.AsyncClient(base_url=QDRANT_URL) as client:
            response = await client.delete(f"/collections/{collection}")
            response.raise_for_status()
        await retriever.client.aclose()
