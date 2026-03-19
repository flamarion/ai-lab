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
            vectors_config=VectorParams(size=768, distance=Distance.COSINE),
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
) -> None:
    """Store chunk vectors with metadata in Qdrant."""
    if not _client:
        raise RuntimeError("Qdrant not initialized")

    points = [
        PointStruct(
            id=str(uuid.uuid4()),
            vector=vector,
            payload={
                "text": chunk["text"],
                "document_id": document_id,
                "source": source,
                "chunk_index": chunk["chunk_index"],
            },
        )
        for chunk, vector in zip(chunks, vectors)
    ]

    _client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)


def search(query_vector: list[float], limit: int = 5) -> list[dict]:
    """Search for similar chunks. Returns list of payloads with scores."""
    if not _client:
        raise RuntimeError("Qdrant not initialized")

    results = _client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        query=query_vector,
        limit=limit,
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
