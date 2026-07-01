"""Phase 4 cross-tenant isolation tests (task 4.6).

These tests verify that:
  1. vector_store.search() NEVER leaks results across org namespaces
  2. search() raises TypeError when org_id is omitted (no silent unscoped query)
  3. store_document() always produces a URI prefixed with {org_id}/

No live Pinecone or S3 connections are required — the Pinecone index is mocked
and the storage tests use the local backend via a temp directory.
"""

import os
import types
import pytest
import tempfile
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORG_A = "acme-corp"
ORG_B = "globex-inc"


def _make_pinecone_match(org_id: str, chunk_id: str = "abc123") -> dict:
    """Synthesise a Pinecone query response match for a given org."""
    return {
        "id": chunk_id,
        "score": 0.9,
        "metadata": {
            "text": "Q4 budget memo content",
            "source_name": "q4_budget.txt",
            "data_source": "pdf_documents",
            "chunk_index": 0,
            "org_id": org_id,
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def mock_vector_store():
    """VectorStore with its Pinecone index replaced by a MagicMock.

    The mock's `query` side_effect records which namespace was requested so
    tests can assert namespace isolation without a live Pinecone connection.
    """
    # Patch at the module level so the import inside VectorStore doesn't fire
    with patch("app.retrieval.vector_store.Pinecone") as MockPinecone, \
         patch("app.retrieval.vector_store.NVIDIAEmbeddings") as MockEmbeddings, \
         patch("app.retrieval.vector_store.SemanticChunker"):

        # Embeddings stub — return a fixed 4096-dim vector
        mock_embed_instance = MagicMock()
        mock_embed_instance.embed_query.return_value = [0.1] * 4096
        mock_embed_instance.embed_documents.return_value = [[0.1] * 4096]
        MockEmbeddings.return_value = mock_embed_instance

        # Pinecone index stub
        mock_index = MagicMock()
        MockPinecone.return_value.Index.return_value = mock_index

        from app.retrieval.vector_store import VectorStore
        from app.models.domain import DataSource

        store = VectorStore.__new__(VectorStore)
        store._pc = MockPinecone.return_value
        store._index = mock_index
        store._embedding_model = mock_embed_instance
        store._chunker = MagicMock()
        store._chunker.create_documents.return_value = [
            types.SimpleNamespace(page_content="chunk text")
        ]

        yield store, mock_index, DataSource


# ---------------------------------------------------------------------------
# Test 1 — vector search never leaks across orgs
# ---------------------------------------------------------------------------

def test_vector_search_never_leaks_across_orgs(mock_vector_store):
    """Seeding org_b's namespace must not appear in org_a's search results.

    This test verifies namespace isolation at the structural level: the mock
    returns org_b metadata only when queried in org_b's namespace, and the
    search() method is called with org_a's namespace — so the mock returns
    nothing for org_a.  The assertion confirms zero cross-namespace hits.
    """
    store, mock_index, DataSource = mock_vector_store

    def namespace_aware_query(**kwargs):
        """Return results only if the namespace matches org_b (simulating isolation)."""
        ns = kwargs.get("namespace", "")
        if ns == ORG_B:
            return {"matches": [_make_pinecone_match(ORG_B)]}
        # org_a namespace has no "Q4 budget" documents
        return {"matches": []}

    mock_index.query.side_effect = namespace_aware_query

    results = store.search(
        query="Q4 budget",
        allowed_sources=[DataSource.PDF_DOCUMENTS],
        org_id=ORG_A,
    )

    # No org_b data should appear in org_a's results
    assert results == [], (
        f"Expected zero results for org_a, got {results} — namespace isolation broken"
    )

    # Confirm the index was queried with org_a's namespace only
    call_kwargs = mock_index.query.call_args.kwargs
    assert call_kwargs["namespace"] == ORG_A, (
        f"Expected namespace={ORG_A!r}, got {call_kwargs['namespace']!r}"
    )


def test_vector_search_returns_own_org_results(mock_vector_store):
    """Control test: org_b's search returns org_b's own results correctly."""
    store, mock_index, DataSource = mock_vector_store

    mock_index.query.return_value = {"matches": [_make_pinecone_match(ORG_B)]}

    results = store.search(
        query="Q4 budget",
        allowed_sources=[DataSource.PDF_DOCUMENTS],
        org_id=ORG_B,
    )

    assert len(results) == 1
    assert results[0].org_id == ORG_B

    # Confirm the index was queried with org_b's namespace
    call_kwargs = mock_index.query.call_args.kwargs
    assert call_kwargs["namespace"] == ORG_B


# ---------------------------------------------------------------------------
# Test 2 — search() requires org_id (no silent unscoped query)
# ---------------------------------------------------------------------------

def test_search_requires_org_id(mock_vector_store):
    """Calling search() without org_id must raise TypeError immediately.

    This is the fail-loudly contract: a missing org_id must never silently
    fall through to an unscoped Pinecone query.
    """
    store, mock_index, DataSource = mock_vector_store

    with pytest.raises(TypeError):
        # org_id omitted — must raise TypeError, not return empty results
        store.search(query="test", allowed_sources=[DataSource.PDF_DOCUMENTS])  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Test 3 — object storage keys are always org-prefixed
# ---------------------------------------------------------------------------

def test_storage_keys_are_org_prefixed():
    """store_document() must return a URI whose path starts with {org_id}/."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.environ["OBJECT_STORAGE_BACKEND"] = "local"
        os.environ["OBJECT_STORAGE_LOCAL_DIR"] = tmpdir

        # Import after env var is set so _local_root() picks it up
        from app.db.storage import store_document

        uri = store_document(
            org_id=ORG_A,
            data_source_id="data_source_1",
            filename="file.pdf",
            file_bytes=b"dummy content",
        )

        # URI must contain the org_id prefix
        assert ORG_A in uri, f"Expected org_id {ORG_A!r} in URI, got {uri!r}"

        # The raw key portion must start with org_id/
        # URI format: file:///abs/path/to/tmpdir/{org_id}/{data_source_id}/{filename}
        # Normalise path separators — Windows uses backslashes in file:// URIs.
        uri_normalised = uri.replace("\\", "/")
        assert f"{ORG_A}/data_source_1/file.pdf" in uri_normalised, (
            f"Expected key pattern '{ORG_A}/data_source_1/file.pdf' in URI {uri_normalised!r}"
        )
