"""Hybrid context aggregation from multiple retrievers."""

import time
from dataclasses import dataclass, field

from app.models.domain import DataSource
from app.models.schemas import Citation, RetrievalTrace
from app.retrieval.csv_retriever import CSVRetriever
from app.retrieval.json_retriever import JSONRetriever
from app.retrieval.vector_store import VectorStore


@dataclass
class RetrievedContext:
    chunks: list[str] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    traces: list[RetrievalTrace] = field(default_factory=list)
    combined_context: str = ""


class ContextAggregator:
    def __init__(
        self,
        vector_store: VectorStore | None = None,
        csv_retriever: CSVRetriever | None = None,
        json_retriever: JSONRetriever | None = None,
    ):
        self.vector_store = vector_store or VectorStore()
        self.csv_retriever = csv_retriever or CSVRetriever()
        self.json_retriever = json_retriever or JSONRetriever()

    def retrieve(
        self,
        query: str,
        allowed_sources: list[DataSource],
        org_id: str,           # required — no default; scopes vector search to this org's namespace
        top_k: int = 5,
    ) -> RetrievedContext:
        context = RetrievedContext()
        all_chunks: list[tuple[str, Citation]] = []

        # Vector retrieval
        start = time.perf_counter()
        try:
            vector_results = self.vector_store.search(query, allowed_sources, org_id=org_id, top_k=top_k)
            latency = (time.perf_counter() - start) * 1000
            context.traces.append(
                RetrievalTrace(
                    data_source=DataSource.PDF_DOCUMENTS,
                    method="vector_semantic_search",
                    result_count=len(vector_results),
                    latency_ms=round(latency, 2),
                    status="success" if vector_results else "no_results",
                )
            )
            for vr in vector_results:
                citation = Citation(
                    source_type="document",
                    source_name=vr.source_name,
                    excerpt=vr.content[:300],
                    relevance_score=round(vr.score, 3),
                    data_source=vr.data_source,
                )
                all_chunks.append((vr.content, citation))
        except Exception as exc:
            context.traces.append(
                RetrievalTrace(
                    data_source=DataSource.PDF_DOCUMENTS,
                    method="vector_semantic_search",
                    result_count=0,
                    latency_ms=round((time.perf_counter() - start) * 1000, 2),
                    status=f"error: {exc}",
                )
            )

        # # Structured retrievers
        # Not required now
        # retriever_configs = [
        #     (self.sql_retriever, "sql_query", DataSource.FINANCIAL_DATABASE),
        #     (self.csv_retriever, "csv_filter", DataSource.OPERATIONAL_DATASETS),
        #     (self.json_retriever, "json_filter", DataSource.AUDIT_LOGS),
        # ]

        # for retriever, method, default_source in retriever_configs:
        #     start = time.perf_counter()
        #     try:
        #         results = retriever.retrieve(query, allowed_sources)
        #         latency = (time.perf_counter() - start) * 1000
        #         context.traces.append(
        #             RetrievalTrace(
        #                 data_source=default_source,
        #                 method=method,
        #                 result_count=len(results),
        #                 latency_ms=round(latency, 2),
        #                 status="success" if results else "no_results",
        #             )
        #         )
        #         for result in results:
        #             citation = Citation(
        #                 source_type=method.split("_")[0],
        #                 source_name=result.source_name,
        #                 excerpt=result.content[:300],
        #                 relevance_score=round(result.score, 3),
        #                 data_source=result.data_source,
        #             )
        #             all_chunks.append((result.content, citation))
        #     except Exception as exc:
        #         context.traces.append(
        #             RetrievalTrace(
        #                 data_source=default_source,
        #                 method=method,
        #                 result_count=0,
        #                 latency_ms=round((time.perf_counter() - start) * 1000, 2),
        #                 status=f"error: {exc}",
        #             )
        #         )

        # Keyword boost: re-rank by query term overlap
        query_terms = set(query.lower().split())
        all_chunks.sort(
            key=lambda item: (
                item[1].relevance_score
                + 0.05 * sum(1 for t in query_terms if t in item[0].lower())
            ),
            reverse=True,
        )

        seen_sources: set[str] = set()
        for chunk, citation in all_chunks[: top_k]:
            source_key = f"{citation.source_name}:{citation.excerpt[:50]}"
            # if source_key in seen_sources:
            #     continue
            # seen_sources.add(source_key)
            context.chunks.append(chunk)
            context.citations.append(citation)

        context.combined_context = "\n\n---\n\n".join(context.chunks)
        return context
