"""Vector store for unstructured document retrieval."""

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

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
        self.settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(self.settings.chroma_persist_dir),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

    @property
    def document_count(self) -> int:
        return self._collection.count()

    def ingest_documents(self, documents_dir: Path | None = None) -> int:
        docs_dir = documents_dir or (self.settings.data_dir / "documents")
        if not docs_dir.exists():
            return 0

        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for doc_path in sorted(docs_dir.glob("*.txt")):
            text = doc_path.read_text(encoding="utf-8")
            chunks = self._chunk_text(text)
            data_source = DOCUMENT_SOURCE_MAP.get(doc_path.name, DataSource.PDF_DOCUMENTS)

            for i, chunk in enumerate(chunks):
                chunk_id = hashlib.md5(f"{doc_path.name}:{i}:{chunk[:50]}".encode()).hexdigest()
                ids.append(chunk_id)
                documents.append(chunk)
                metadatas.append(
                    {
                        "source_name": doc_path.name,
                        "data_source": data_source.value,
                        "chunk_index": i,
                    }
                )

        if ids:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(ids)

    def ingest_chunks(self, chunks: list[str], filename: str, data_source: DataSource) -> int:
        """Ingest a list of pre-parsed/pre-chunked text strings directly into the collection."""
        ids: list[str] = []
        documents: list[str] = []
        metadatas: list[dict] = []

        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{filename}:{i}:{chunk[:50]}".encode()).hexdigest()
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append(
                {
                    "source_name": filename,
                    "data_source": data_source.value,
                    "chunk_index": i,
                }
            )

        if ids:
            self._collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(ids)

    def search(
        self,
        query: str,
        allowed_sources: list[DataSource],
        top_k: int = 5,
    ) -> list[VectorResult]:
        if not allowed_sources or self._collection.count() == 0:
            return []

        source_values = [s.value for s in allowed_sources]
        where_filter = {"data_source": {"$in": source_values}} if source_values else None

        try:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()),
                where=where_filter,
            )
        except Exception:
            results = self._collection.query(
                query_texts=[query],
                n_results=min(top_k, self._collection.count()),
            )

        vector_results: list[VectorResult] = []
        if not results["documents"] or not results["documents"][0]:
            return vector_results

        for doc, meta, dist, doc_id in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
            results["ids"][0],
        ):
            data_source = DataSource(meta.get("data_source", DataSource.PDF_DOCUMENTS.value))
            if data_source not in allowed_sources:
                continue
            score = max(0.0, 1.0 - dist)
            vector_results.append(
                VectorResult(
                    content=doc,
                    source_name=meta.get("source_name", "unknown"),
                    data_source=data_source,
                    score=score,
                    chunk_id=doc_id,
                )
            )

        return sorted(vector_results, key=lambda r: r.score, reverse=True)[:top_k]

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
