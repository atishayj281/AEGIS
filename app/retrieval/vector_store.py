"""Vector store for unstructured document retrieval."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from pymilvus import MilvusClient
from pymilvus.model.dense import DefaultEmbeddingFunction

from app.config import Settings, get_settings
from app.models.domain import DataSource


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

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.settings.milvus_db_path.parent.mkdir(parents=True, exist_ok=True)
        self._client = MilvusClient(str(self.settings.milvus_db_path))
        self._embedding_fn = DefaultEmbeddingFunction()
        
        # Create collection if it doesn't exist
        if not self._client.has_collection(self.COLLECTION_NAME):
            self._client.create_collection(
                collection_name=self.COLLECTION_NAME,
                dimension=self._embedding_fn.dim,
                metric_type="COSINE",
                id_type="string", # We use hash strings for ids
                max_length=64 # MD5 hashes are 32 chars
            )

    @property
    def document_count(self) -> int:
        if not self._client.has_collection(self.COLLECTION_NAME):
            return 0
        res = self._client.query(
            collection_name=self.COLLECTION_NAME,
            filter="",
            output_fields=["count(*)"]
        )
        return res[0].get("count(*)", 0) if res else 0

    def ingest_documents(self, documents_dir: Path | None = None) -> int:
        docs_dir = documents_dir or (self.settings.data_dir / "documents")
        if not docs_dir.exists():
            return 0

        chunks_to_insert = []
        for doc_path in sorted(docs_dir.glob("*.txt")):
            text = doc_path.read_text(encoding="utf-8")
            chunks = self._chunk_text(text)
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
        embeddings = self._embedding_fn.encode_documents(texts)
        
        data = []
        for (chunk, filename, data_source_val, chunk_index), emb in zip(chunks_to_insert, embeddings):
            chunk_id = hashlib.md5(f"{filename}:{chunk_index}:{chunk[:50]}".encode()).hexdigest()
            data.append({
                "id": chunk_id,
                "vector": emb,
                "text": chunk,
                "source_name": filename,
                "data_source": data_source_val,
                "chunk_index": chunk_index
            })

        if data:
            self._client.upsert(
                collection_name=self.COLLECTION_NAME,
                data=data
            )
        return len(data)

    def search(
        self,
        query: str,
        allowed_sources: list[DataSource],
        top_k: int = 5,
    ) -> list[VectorResult]:
        if not allowed_sources or not self._client.has_collection(self.COLLECTION_NAME):
            return []

        source_values = [s.value for s in allowed_sources]
        # Build Milvus filter expression
        source_values_str = ", ".join(f"'{v}'" for v in source_values)
        filter_expr = f"data_source in [{source_values_str}]" if source_values else ""

        query_vectors = self._embedding_fn.encode_queries([query])

        try:
            results = self._client.search(
                collection_name=self.COLLECTION_NAME,
                data=query_vectors,
                filter=filter_expr,
                limit=top_k,
                output_fields=["text", "source_name", "data_source"]
            )
        except Exception:
            results = self._client.search(
                collection_name=self.COLLECTION_NAME,
                data=query_vectors,
                limit=top_k,
                output_fields=["text", "source_name", "data_source"]
            )

        vector_results: list[VectorResult] = []
        if not results or not results[0]:
            return vector_results

        for match in results[0]:
            entity = match.get("entity", {})
            data_source = DataSource(entity.get("data_source", DataSource.PDF_DOCUMENTS.value))
            if data_source not in allowed_sources:
                continue
            
            # Milvus distances vary by metric type. With COSINE, distance in pymilvus is usually 1 - cosine_similarity
            # Or cosine similarity itself depending on version. Let's use the distance directly if it's cosine similarity.
            # Usually PyMilvus returns cosine similarity for COSINE metric.
            score = max(0.0, float(match.get("distance", 0.0)))
            
            vector_results.append(
                VectorResult(
                    content=entity.get("text", ""),
                    source_name=entity.get("source_name", "unknown"),
                    data_source=data_source,
                    score=score,
                    chunk_id=str(match.get("id"))
                )
            )

        return sorted(vector_results, key=lambda r: r.score, reverse=True)

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
