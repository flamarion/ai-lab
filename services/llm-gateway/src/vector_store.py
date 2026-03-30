"""Vector store layer — Qdrant client for RAG chunk storage and search."""

import logging
import uuid

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from ai_lab_common.config import settings

logger = logging.getLogger(__name__)

_client: QdrantClient | None = None


def init_store() -> None:
    """Connect to Qdrant and ensure the collection exists."""
    global _client
    _client = QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT)

    if not _client.collection_exists(settings.QDRANT_COLLECTION):
        _client.create_collection(
            collection_name=settings.QDRANT_COLLECTION,
            vectors_config=VectorParams(size=settings.EMBED_DIMENSION, distance=Distance.COSINE),
        )
        logger.info("Created Qdrant collection: %s", settings.QDRANT_COLLECTION)
    else:
        logger.info("Qdrant collection exists: %s", settings.QDRANT_COLLECTION)


def close_store() -> None:
    """Close the Qdrant client."""
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("Qdrant client closed")


def is_available() -> bool:
    """Check if the Qdrant client is initialized."""
    return _client is not None


def upsert_chunks(
    chunks: list[dict],
    vectors: list[list[float]],
    document_id: str,
    source: str,
    user_id: str | None = None,
    is_private: bool = False,
) -> None:
    """Store chunk vectors with metadata in Qdrant."""
    if not _client:
        raise RuntimeError("Qdrant not initialized")

    points = [
        PointStruct(
            id=uuid.uuid4().hex,
            vector=vector,
            payload={
                "text": chunk["text"],
                "document_id": document_id,
                "source": source,
                "chunk_index": chunk["chunk_index"],
                "user_id": user_id or "",
                "is_private": is_private,
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]

    _client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)


def search(
    query_vector: list[float], limit: int = 5, user_id: str | None = None,
) -> list[dict]:
    """Search for similar chunks visible to the user.

    Returns shared documents (is_private=false or missing) plus the user's
    own private documents.  Pre-existing chunks without is_private are
    treated as shared.
    """
    if not _client:
        raise RuntimeError("Qdrant not initialized")

    from qdrant_client.models import (
        Filter, FieldCondition, IsNullCondition, MatchValue, PayloadField,
    )

    # Build a filter: shared docs OR user's own docs OR pre-migration docs.
    # Three `should` clauses (any match passes):
    #   1. is_private == false  — explicitly shared documents
    #   2. user_id == caller    — user's own docs (private or shared)
    #   3. is_private is null   — pre-migration chunks that lack the field
    query_filter = None
    if user_id:
        query_filter = Filter(
            should=[
                FieldCondition(key="is_private", match=MatchValue(value=False)),
                FieldCondition(key="user_id", match=MatchValue(value=user_id)),
                IsNullCondition(is_null=PayloadField(key="is_private")),
            ],
        )

    results = _client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=query_vector,
        limit=limit,
        query_filter=query_filter,
    )

    return [
        {
            "text": point.payload["text"],
            "source": point.payload.get("source", ""),
            "score": point.score,
            "document_id": point.payload.get("document_id", ""),
            "chunk_index": point.payload.get("chunk_index", 0),
        }
        for point in results.points
    ]


def delete_by_document(document_id: str) -> None:
    """Remove all vectors belonging to a document."""
    if not _client:
        raise RuntimeError("Qdrant not initialized")

    from qdrant_client.models import Filter, FieldCondition, MatchValue

    _client.delete(
        collection_name=settings.QDRANT_COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
        ),
    )
