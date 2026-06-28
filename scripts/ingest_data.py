"""Data ingestion script for the vector store."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.retrieval.vector_store import VectorStore


def main():
    settings = get_settings()
    print("Enterprise RAG - Data Ingestion")
    print("=" * 40)

    vector_store = VectorStore(settings)
    count = vector_store.ingest_documents()
    print(f"Ingested {count} document chunks")

    print("\nData sources ready:")
    print(f"  - Documents: {settings.data_dir / 'documents'}")
    print(f"  - CSV:       {settings.data_dir / 'csv'}")
    print(f"  - JSON logs: {settings.data_dir / 'json'}")
    print(f"  - Vector DB: {settings.qdrant_url}")


if __name__ == "__main__":
    main()