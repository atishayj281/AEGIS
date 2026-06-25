"""Vector store for unstructured document retrieval (Qdrant-backed)."""

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from app.config import Settings, get_settings
from app.models.domain import DataSource

from langchain_experimental.text_splitter import SemanticChunker
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings


@dataclass
class VectorResult:
    content: str
    source_name: str
    data_source: DataSource
    score: float
    chunk_id: str


DOCUMENT_SOURCE_MAP = {
    "Compliance_Audit_Report_2026.txt": DataSource.COMPLIANCE_RECORDS,
    "GDPR_Retention_Policy.txt": DataSource.COMPLIANCE_RECORDS,
    "Infrastructure_Audit_Report_2026.txt": DataSource.INFRASTRUCTURE_REPORTS,
    "Employee_Handbook_Policies.txt": DataSource.PUBLIC_POLICIES,
}


class VectorStore:
    COLLECTION_NAME = "enterprise_documents"

    # Payload fields that get filtered on in `search()` must have an explicit
    # index in Qdrant — unlike the vector itself, payload fields are never
    # auto-indexed. Add any new filterable field here.
    FILTERABLE_PAYLOAD_FIELDS = {
        "data_source": PayloadSchemaType.KEYWORD,
    }

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

        # `milvus_db_path` is a holdover name from before the Milvus->Qdrant
        # migration, but it's still used as a generic local scratch path
        # (e.g. for any local file-based fallback), so we keep honoring it.
        # if getattr(self.settings, "milvus_db_path", None):
        #     self.settings.milvus_db_path.parent.mkdir(parents=True, exist_ok=True)

        qdrant_url = getattr(self.settings, "qdrant_url", None)
        qdrant_api_key = getattr(self.settings, "qdrant_api_key", None)

        self._client = QdrantClient(
            url=qdrant_url,
            api_key=qdrant_api_key,
        )
        self._embedding_model = NVIDIAEmbeddings(
                                    model="nvidia/nv-embed-v1", 
                                    api_key= self.settings.nvidia_api_key, 
                                    truncate="NONE", 
                                    )


        # Semantic chunker reuses the same embedding model instance instead of
        # creating a fresh (and misconfigured) one on every call.
        self._chunker = SemanticChunker(
            embeddings=self._embedding_model,
            breakpoint_threshold_type="percentile",
            breakpoint_threshold_amount=90,
        )

        # Collection is created lazily on first ingest, once we know the
        # embedding dimension. If it already exists from a previous run,
        # make sure required payload indexes are present too — covers the
        # case where the collection was created before this fix existed.
        if self._client.collection_exists(self.COLLECTION_NAME):
            self._ensure_payload_indexes()

    @property
    def document_count(self) -> int:
        if not self._client.collection_exists(self.COLLECTION_NAME):
            return 0
        info = self._client.get_collection(self.COLLECTION_NAME)
        return info.points_count or 0


    def ingest_documents(self, documents_dir: Path | None = None) -> int:
        docs_dir = documents_dir or (self.settings.data_dir / "documents")
        if not docs_dir.exists():
            return 0

        chunks_to_insert: list[tuple[str, str, str, int]] = []
        for doc_path in sorted(docs_dir.glob("*.txt")):
            text = doc_path.read_text(encoding="utf-8")
            chunks = self._semantic_chunk_text(text)
            data_source = DOCUMENT_SOURCE_MAP.get(doc_path.name, DataSource.PDF_DOCUMENTS)

            for i, chunk in enumerate(chunks):
                chunks_to_insert.append((chunk, doc_path.name, data_source.value, i))

        return self._ingest_chunk_data(chunks_to_insert)

    def ingest_chunks(self, chunks: list[str], filename: str, data_source: DataSource) -> int:
        """Ingest a list of pre-parsed/pre-chunked text strings directly into the collection."""
        chunks_to_insert = [(chunk, filename, data_source.value, i) for i, chunk in enumerate(chunks)]
        return self._ingest_chunk_data(chunks_to_insert)

    def _ingest_chunk_data(self, chunks_to_insert: list[tuple[str, str, str, int]]) -> int:
        if not chunks_to_insert:
            return 0
        texts = [c[0] for c in chunks_to_insert]

        vectors = self._get_embeddings(texts, is_query=False)
        if not vectors:
            return 0

        dim = len(vectors[0])
        self._ensure_collection(dim)

        points = []
        for (chunk, filename, data_source_val, chunk_index), vector in zip(chunks_to_insert, vectors):
            chunk_id = hashlib.md5(f"{filename}:{chunk_index}:{chunk[:50]}".encode()).hexdigest()
            points.append(
                PointStruct(
                    id=chunk_id,
                    payload={
                        "text": chunk,
                        "source_name": filename,
                        "data_source": data_source_val,
                        "chunk_index": chunk_index,
                    },
                    vector=list(vector),
                )
            )

        if points:
            self._client.upsert(collection_name=self.COLLECTION_NAME, points=points)
        return len(points)

    def _ensure_collection(self, dim: int) -> None:
        if self._client.collection_exists(self.COLLECTION_NAME):
            return
        self._client.create_collection(
            collection_name=self.COLLECTION_NAME,
            vectors_config=VectorParams(size=dim, distance=Distance.COSINE),
        )
        self._ensure_payload_indexes()

    def _ensure_payload_indexes(self) -> None:
        """Create payload indexes for every field `search()` filters on.

        Qdrant requires an explicit index on any payload field used inside a
        Filter/FieldCondition — it is not created automatically alongside the
        vector index. Skipping this causes search() to fail with:
            Bad request: Index required but not found for "data_source" ...
        This is idempotent: re-creating an existing index is a safe no-op
        (Qdrant returns success rather than erroring).
        """
        existing = self._client.get_collection(self.COLLECTION_NAME).payload_schema or {}
        for field_name, schema_type in self.FILTERABLE_PAYLOAD_FIELDS.items():
            if field_name in existing:
                continue
            self._client.create_payload_index(
                collection_name=self.COLLECTION_NAME,
                field_name=field_name,
                field_schema=schema_type,
            )

    def _get_embeddings(self, texts: list[str], is_query: bool = False) -> list[list[float]]:
        """Embed a batch of texts (documents) or a single query string."""
        if not texts:
            return []

        try:
            if is_query:
                # Most NVIDIAEmbeddings versions expose embed_query for single strings.
                if hasattr(self._embedding_model, "embed_query"):
                    return [list(self._embedding_model.embed_query(texts[0]))]
                res = self._embedding_model.embed_documents(texts)
            else:
                res = self._embedding_model.embed_documents(texts)

            if isinstance(res, dict) and "embeddings" in res:
                return [list(v) for v in res["embeddings"]]
            if isinstance(res, list) and res and isinstance(res[0], (list, tuple)):
                return [list(r) for r in res]

            import numpy as _np

            return [_np.asarray(r).tolist() for r in res]
        except Exception:
            return []

    def search(
        self,
        query: str,
        allowed_sources: list[DataSource],
        top_k: int = 5,
    ) -> list[VectorResult]:
        if not allowed_sources or not self._client.collection_exists(self.COLLECTION_NAME):
            return []

        query_vectors = self._get_embeddings([query], is_query=True)
        if not query_vectors:
            return []
        query_vector = query_vectors[0]

        source_values = [s.value for s in allowed_sources]
        query_filter = Filter(
            must=[FieldCondition(key="data_source", match=MatchAny(any=source_values))]
        )

        results = self._client.query_points(
            collection_name=self.COLLECTION_NAME,
            query=query_vector,
            query_filter=query_filter,
            limit=top_k,
            with_payload=True,
        ).points

        vector_results: list[VectorResult] = []
        for match in results:
            payload = match.payload or {}
            try:
                data_source = DataSource(payload.get("data_source", DataSource.PDF_DOCUMENTS.value))
            except ValueError:
                continue
            if data_source not in allowed_sources:
                continue

            vector_results.append(
                VectorResult(
                    content=payload.get("text", ""),
                    source_name=payload.get("source_name", "unknown"),
                    data_source=data_source,
                    score=float(match.score),
                    chunk_id=str(match.id),
                )
            )

        print(f"\n\n{"-"*20}\n{vector_results}\n{"-"*20}")

        return sorted(vector_results, key=lambda r: r.score, reverse=True)

    def _semantic_chunk_text(self, raw_text: str) -> list[str]:
        cleaned_text = re.sub(r" +", " ", raw_text)
        cleaned_text = re.sub(r"\n+", "\n\n", cleaned_text)
        lines = [line.strip() for line in cleaned_text.split("\n")]
        final_text = "\n".join(lines)

        document_chunks = self._chunker.create_documents([final_text])
        return [chunk.page_content for chunk in document_chunks]

    def _chunk_text(self, text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        chunks: list[str] = []
        current = ""

        for para in paragraphs:
            if len(current) + len(para) + 1 <= chunk_size:
                current = f"{current}\n\n{para}".strip() if current else para
            else:
                if current:
                    chunks.append(current)
                if len(para) <= chunk_size:
                    current = para
                else:
                    for i in range(0, len(para), chunk_size - overlap):
                        chunks.append(para[i : i + chunk_size])
                    current = ""

        if current:
            chunks.append(current)
        return chunks