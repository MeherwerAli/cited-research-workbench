import hashlib
import math
import re
import uuid
from collections import Counter
from typing import Protocol

import httpx

from .models import Chunk, SearchHit

VECTOR_SIZE = 256
STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "do",
        "does",
        "for",
        "how",
        "in",
        "is",
        "of",
        "on",
        "the",
        "to",
        "what",
        "when",
        "where",
        "which",
        "who",
        "why",
    }
)


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def content_tokens(text: str) -> set[str]:
    return {token for token in tokens(text) if token not in STOP_WORDS}


def dense_vector(text: str) -> list[float]:
    vector = [0.0] * VECTOR_SIZE
    for token in tokens(text):
        index = int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % VECTOR_SIZE
        vector[index] += 1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


def sparse_vector(text: str) -> tuple[list[int], list[float]]:
    counts = Counter(tokens(text))
    entries = sorted(
        (
            int.from_bytes(hashlib.sha256(token.encode()).digest()[:4], "big") % 1_000_003,
            float(count),
        )
        for token, count in counts.items()
    )
    return [item[0] for item in entries], [item[1] for item in entries]


def cosine(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=True))


class Retriever(Protocol):
    async def index(self, chunks: list[Chunk]) -> None: ...

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]: ...


class Reranker(Protocol):
    async def scores(self, query: str, chunks: list[Chunk]) -> list[float]: ...


class HTTPReranker:
    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=10)

    async def scores(self, query: str, chunks: list[Chunk]) -> list[float]:
        response = await self.client.post(
            "/rerank",
            json={"query": query, "documents": [chunk.text for chunk in chunks]},
        )
        response.raise_for_status()
        results = response.json()["results"]
        by_index = {int(item["index"]): float(item["relevance_score"]) for item in results}
        if set(by_index) != set(range(len(chunks))):
            raise ValueError("reranker response did not score every chunk")
        return [by_index[index] for index in range(len(chunks))]


async def rerank_with_fallback(
    query: str, hits: list[SearchHit], reranker: Reranker | None
) -> list[SearchHit]:
    if reranker is None:
        return sorted(hits, key=lambda item: (-item.rerank_score, -item.fused_score, item.chunk.id))
    try:
        scores = await reranker.scores(query, [hit.chunk for hit in hits])
    except (httpx.HTTPError, KeyError, TypeError, ValueError):
        return sorted(hits, key=lambda item: (-item.fused_score, item.chunk.id))
    rescored = [
        hit.model_copy(update={"rerank_score": score})
        for hit, score in zip(hits, scores, strict=True)
    ]
    return sorted(rescored, key=lambda item: (-item.rerank_score, -item.fused_score, item.chunk.id))


class InMemoryHybridRetriever:
    def __init__(self) -> None:
        self._chunks: dict[str, Chunk] = {}

    async def index(self, chunks: list[Chunk]) -> None:
        self._chunks.update((chunk.id, chunk) for chunk in chunks)

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        query_tokens = content_tokens(query)
        query_dense = dense_vector(query)
        scored: list[tuple[Chunk, float, float]] = []
        for chunk in self._chunks.values():
            chunk_tokens = tokens(chunk.text)
            sparse = sum(1 for token in chunk_tokens if token in query_tokens) / max(
                1, len(chunk_tokens)
            )
            dense = cosine(query_dense, dense_vector(chunk.text))
            scored.append((chunk, dense, sparse))
        dense_ranked = sorted(scored, key=lambda item: (-item[1], item[0].id))
        sparse_ranked = sorted(scored, key=lambda item: (-item[2], item[0].id))
        dense_ranks = {item[0].id: rank for rank, item in enumerate(dense_ranked, start=1)}
        sparse_ranks = {item[0].id: rank for rank, item in enumerate(sparse_ranked, start=1)}
        hits: list[SearchHit] = []
        for chunk, _, _ in scored:
            fused = 1 / (60 + dense_ranks[chunk.id]) + 1 / (60 + sparse_ranks[chunk.id])
            overlap = len(query_tokens.intersection(content_tokens(chunk.text))) / max(
                1, len(query_tokens)
            )
            hits.append(
                SearchHit(
                    chunk=chunk,
                    dense_rank=dense_ranks[chunk.id],
                    sparse_rank=sparse_ranks[chunk.id],
                    fused_score=fused,
                    rerank_score=overlap,
                )
            )
        return sorted(
            hits, key=lambda item: (-item.rerank_score, -item.fused_score, item.chunk.id)
        )[:limit]


class QdrantHybridRetriever:
    """Qdrant Query API adapter using deterministic dense and sparse vectors plus RRF."""

    def __init__(
        self,
        base_url: str,
        collection: str = "portfolio-research",
        reranker: Reranker | None = None,
    ) -> None:
        self.collection = collection
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=20)
        self.reranker = reranker

    async def index(self, chunks: list[Chunk]) -> None:
        collection_response = await self.client.put(
            f"/collections/{self.collection}",
            json={
                "vectors": {"dense": {"size": VECTOR_SIZE, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {"index": {"on_disk": False}}},
            },
        )
        if collection_response.status_code != 409:
            collection_response.raise_for_status()
        points = []
        for chunk in chunks:
            indices, values = sparse_vector(chunk.text)
            points.append(
                {
                    "id": str(uuid.UUID(hex=chunk.id.removeprefix("chk_"))),
                    "vector": {
                        "dense": dense_vector(chunk.text),
                        "sparse": {"indices": indices, "values": values},
                    },
                    "payload": chunk.model_dump(),
                }
            )
        response = await self.client.put(
            f"/collections/{self.collection}/points",
            params={"wait": "true"},
            json={"points": points},
        )
        response.raise_for_status()

    async def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        indices, values = sparse_vector(query)
        response = await self.client.post(
            f"/collections/{self.collection}/points/query",
            json={
                "prefetch": [
                    {"query": dense_vector(query), "using": "dense", "limit": 20},
                    {
                        "query": {"indices": indices, "values": values},
                        "using": "sparse",
                        "limit": 20,
                    },
                ],
                "query": {"fusion": "rrf"},
                "limit": max(limit * 3, 10),
                "with_payload": True,
            },
        )
        response.raise_for_status()
        query_tokens = content_tokens(query)
        hits = []
        for point in response.json()["result"]["points"]:
            chunk = Chunk.model_validate(point["payload"])
            overlap = len(query_tokens.intersection(content_tokens(chunk.text))) / max(
                1, len(query_tokens)
            )
            hits.append(
                SearchHit(chunk=chunk, fused_score=float(point["score"]), rerank_score=overlap)
            )
        return (await rerank_with_fallback(query, hits, self.reranker))[:limit]
