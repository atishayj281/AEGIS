"""Data ingestion script for vector store and database."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.retrieval.sql_retriever import SQLRetriever
from app.retrieval.vector_store import VectorStore


def main():
    settings = get_settings()
    print("Enterprise RAG - Data Ingestion")
    print("=" * 40)

    vector_store = VectorStore(settings)
    count = vector_store.ingest_documents()
    print(f"Ingested {count} document chunks")

    sql = SQLRetriever(settings)
    print(f"SQLite database initialized at {settings.sqlite_path}")

    print("\nData sources ready:")
    print(f"  - Documents: {settings.data_dir / 'documents'}")
    print(f"  - CSV:       {settings.data_dir / 'csv'}")
    print(f"  - JSON logs: {settings.data_dir / 'json'}")
    print(f"  - SQLite:    {settings.sqlite_path}")
    print(f"  - Vector DB: {settings.chroma_persist_dir}")


if __name__ == "__main__":
    main()
