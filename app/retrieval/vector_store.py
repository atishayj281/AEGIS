"""Vector store for unstructured document retrieval (Pinecone-backed).

Tenant isolation: one Pinecone namespace per org_id.  A query or upsert is
always scoped to exactly one namespace — the index itself enforces the
boundary, not a per-call-site filter that can be forgotten.

Every public method that touches the index requires `org_id` with NO default
value.  Callers that omit it get a TypeError at call time, not a silent
cross-tenant operation.
"""

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from pinecone.grpc import PineconeGRPC as Pinecone
from pinecone import ServerlessSpec

from app.config import Settings, get_settings
from app.models.domain import DataSource

from langchain_experimental.text_splitter import SemanticChunker
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings

# Embedding dimension for nvidia/nv-embed-v1 (confirmed from NVIDIA model card)
_EMBEDDING_DIM = 4096


@dataclass
class VectorResult:
    content: str
    source_name: str
    data_source: DataSource
    score: float
    chunk_id: str
    org_id: str  # Added for Phase 4 cross-tenant isolation assertions


DOCUMENT_SOURCE_MAP = {
    # "Compliance_Audit_Report_2026.txt": DataSource.COMPLIANCE_RECORDS,
    # "GDPR_Retention_Policy.txt": DataSource.COMPLIANCE_RECORDS,
    # "Infrastructure_Audit_Report_2026.txt": DataSource.INFRASTRUCTURE_REPORTS,
    # "Employee_Handbook_Policies.txt": DataSource.PUBLIC_POLICIES,
}


class VectorStore:
    # Single index, multi-namespace.  The index name is read from settings so
    # tests can point at a different index without changing code.
    INDEX_NAME_SETTING = "aegis-documents"

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

        api_key = getattr(self.settings, "pinecone_api_key", None) or os.environ.get(
            "PINECONE_API_KEY"
        )
        index_name = getattr(self.settings, "pinecone_index_name", None) or os.environ.get(
            "PINECONE_INDEX_NAME", "aegis-documents"
        )

        self._pc = Pinecone(api_key=api_key)
        self._index = self._pc.Index(index_name)

        self._embedding_model = NVIDIAEmbeddings(
            model="nvidia/nv-embed-v1",
            api_key=self.settings.nvidia_api_key,
            truncate="NONE",
        )

        # Semantic chunker reuses the same embedding model instance instead of
        # creating a fresh one on every call.
        self._chunker = SemanticChunker(
            embeddings=self._embedding_model,
            breakpoint_threshold_type="percentile",
            breakpoint_threshold_amount=90,
        )

    # ------------------------------------------------------------------
    # Public read helpers
    # ------------------------------------------------------------------

    @property
    def document_count(self) -> int:
        """Total vector count across all namespaces in the index."""
        try:
            stats = self._index.describe_index_stats()
            return stats.get("total_vector_count", 0)
        except Exception:
            return 0

    def document_count_for_org(self, org_id: str) -> int:
        """Vector count for a single org's namespace."""
        try:
            stats = self._index.describe_index_stats()
            ns = stats.get("namespaces", {}).get(org_id, {})
            return ns.get("vector_count", 0)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Ingest
    # ------------------------------------------------------------------

    def ingest_documents(self, org_id: str, documents_dir: Path | None = None) -> int:
        """Ingest all .txt files in documents_dir into org_id's namespace."""
        docs_dir = documents_dir or (self.settings.data_dir / "documents")
        if not docs_dir.exists():
            return 0

        chunks_to_insert: list[tuple[str, str, str, int]] = []
        for doc_path in sorted(docs_dir.glob("*.txt")):
            text = doc_path.read_text(encoding="utf-8")
            chunks = self._semantic_chunk_text(text)
            data_source = DOCUMENT_SOURCE_MAP.get(
                doc_path.name, DataSource.PDF_DOCUMENTS
            )
            for i, chunk in enumerate(chunks):
                chunks_to_insert.append((chunk, doc_path.name, data_source.value, i))

        return self._ingest_chunk_data(org_id, chunks_to_insert)

    def ingest_chunks(
        self,
        org_id: str,
        chunks: list[str],
        filename: str,
        data_source: DataSource,
    ) -> int:
        """Ingest pre-parsed chunks directly into org_id's namespace."""
        chunks_to_insert = [
            (chunk, filename, data_source.value, i) for i, chunk in enumerate(chunks)
        ]
        return self._ingest_chunk_data(org_id, chunks_to_insert)

    def _ingest_chunk_data(
        self, org_id: str, chunks_to_insert: list[tuple[str, str, str, int]]
    ) -> int:
        if not chunks_to_insert:
            return 0

        texts = [c[0] for c in chunks_to_insert]
        vectors = self._get_embeddings(texts, is_query=False)
        if not vectors:
            return 0

        records = []
        for (chunk, filename, data_source_val, chunk_index), vector in zip(
            chunks_to_insert, vectors
        ):
            # Deterministic ID: same chunk always produces the same ID so
            # re-ingestion is a safe upsert, not a duplicate insert.
            chunk_id = hashlib.md5(
                f"{filename}:{chunk_index}:{chunk[:50]}".encode()
            ).hexdigest()

            records.append(
                {
                    "id": chunk_id,
                    "values": vector,
                    "metadata": {
                        "text": chunk,
                        "source_name": filename,
                        "data_source": data_source_val,
                        "chunk_index": chunk_index,
                        "org_id": org_id,
                    },
                }
            )

        if records:
            # Pinecone upsert into the org's namespace.
            # Batch in groups of 100 to stay well under the 2 MB request limit.
            batch_size = 100
            for i in range(0, len(records), batch_size):
                self._index.upsert(
                    vectors=records[i : i + batch_size],
                    namespace=org_id,
                )

        return len(records)

    # ------------------------------------------------------------------
    # Search  (task 4.3 — sole entry point for all Pinecone queries)
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        allowed_sources: list[DataSource],
        org_id: str,          # required — no default
        top_k: int = 5,
    ) -> list[VectorResult]:
        """Query the index scoped to org_id's namespace.

        This is the ONLY function in the codebase that calls the Pinecone
        query API directly.  All other code must go through this method.
        If you need a search variant that cannot be expressed here, extend
        this method rather than adding a second call site.
        """
        if not allowed_sources:
            return []

        query_vectors = self._get_embeddings([query], is_query=True)
        if not query_vectors:
            return []

        source_values = [s.value for s in allowed_sources]

        # Metadata filter: data_source must be in allowed_sources.
        # org_id isolation is handled by the namespace — the filter is a
        # defence-in-depth layer, not the primary isolation mechanism.
        query_filter = {"data_source": {"$in": source_values}}

        response = self._index.query(
            vector=query_vectors[0],
            filter=query_filter,
            top_k=top_k,
            include_metadata=True,
            namespace=org_id,
        )

        vector_results: list[VectorResult] = []
        for match in response.get("matches", []):
            metadata = match.get("metadata", {})
            try:
                data_source = DataSource(
                    metadata.get("data_source", DataSource.PDF_DOCUMENTS.value)
                )
            except ValueError:
                continue
            if data_source not in allowed_sources:
                continue

            vector_results.append(
                VectorResult(
                    content=metadata.get("text", ""),
                    source_name=metadata.get("source_name", "unknown"),
                    data_source=data_source,
                    score=float(match.get("score", 0.0)),
                    chunk_id=str(match.get("id", "")),
                    org_id=metadata.get("org_id", org_id),
                )
            )

        return sorted(vector_results, key=lambda r: r.score, reverse=True)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_by_source(self, org_id: str, source_name: str) -> None:
        """Delete all vectors for a given filename within org_id's namespace.

        Routes deletes through VectorStore so routes.py never holds a direct
        Pinecone client reference (task 4.3 requirement).
        """
        # Pinecone serverless supports delete-by-metadata via delete(filter=...)
        # on indexes with deletion_protection disabled (the default).
        try:
            self._index.delete(
                filter={"source_name": {"$eq": source_name}},
                namespace=org_id,
            )
        except Exception as exc:
            # Non-fatal: log and continue so the file-system delete still
            # succeeds even if the vector delete partially fails.
            print(f"Warning: vector delete for {source_name!r} in ns {org_id!r}: {exc}")

    def delete_namespace(self, org_id: str) -> None:
        """Delete every vector in org_id's namespace (used by Phase 6 org deletion)."""
        try:
            self._index.delete(delete_all=True, namespace=org_id)
        except Exception as exc:
            print(f"Warning: namespace delete for org {org_id!r}: {exc}")

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    def _get_embeddings(
        self, texts: list[str], is_query: bool = False
    ) -> list[list[float]]:
        if not texts:
            return []
        try:
            if is_query and hasattr(self._embedding_model, "embed_query"):
                return [list(self._embedding_model.embed_query(texts[0]))]

            res = self._embedding_model.embed_documents(texts)

            if isinstance(res, dict) and "embeddings" in res:
                return [list(v) for v in res["embeddings"]]
            if isinstance(res, list) and res and isinstance(res[0], (list, tuple)):
                return [list(r) for r in res]

            import numpy as _np

            return [_np.asarray(r).tolist() for r in res]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Chunking helpers (vendor-agnostic, unchanged from prior implementation)
    # ------------------------------------------------------------------

    def _semantic_chunk_text(self, raw_text: str) -> list[str]:
        cleaned_text = re.sub(r" +", " ", raw_text)
        cleaned_text = re.sub(r"\n+", "\n\n", cleaned_text)
        lines = [line.strip() for line in cleaned_text.split("\n")]
        final_text = "\n".join(lines)
        document_chunks = self._chunker.create_documents([final_text])
        return [chunk.page_content for chunk in document_chunks]

    def _chunk_text(
        self, text: str, chunk_size: int = 500, overlap: int = 50
    ) -> list[str]:
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