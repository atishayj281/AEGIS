"""Celery tasks for background processing."""

import os
from celery import Celery
from app.document.parser import DocumentParser
from app.retrieval.vector_store import get_vector_store
from app.models.domain import DataSource

redis_url = os.environ.get("REDIS_URL", "redis://redis:6379/0")
celery_app = Celery("ingestion", broker=redis_url, backend=redis_url)

@celery_app.task(name="app.tasks.ingestion.process_document")
def process_document(org_id: str, data_source_val: str, filename: str, ext: str, file_bytes: bytes):
    vector_store = get_vector_store()
    data_source = DataSource(data_source_val)

    try:
        chunks = []
        if ext in [".txt", ".md", ".log"]:
            text = DocumentParser.parse_txt(file_bytes)
            chunks = vector_store._semantic_chunk_text(text)
        elif ext == ".pdf":
            text = DocumentParser.parse_pdf(file_bytes)
            chunks = vector_store._semantic_chunk_text(text)
        elif ext == ".docx":
            text = DocumentParser.parse_docx(file_bytes)
            chunks = vector_store._semantic_chunk_text(text)
        elif ext == ".csv":
            chunks = DocumentParser.parse_csv(file_bytes)
        elif ext in [".xlsx", ".xls"]:
            chunks = DocumentParser._semantic_chunk_text(file_bytes)
        elif ext == ".json":
            chunks = DocumentParser.parse_json(file_bytes)
        elif ext in [".png", ".jpg", ".jpeg"]:
            text = DocumentParser.parse_image(file_bytes, filename)
            chunks = vector_store._semantic_chunk_text(text)

        chunks_ingested = vector_store.ingest_chunks(org_id, chunks, filename, data_source)
        return {"status": "success", "chunks_ingested": chunks_ingested}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
