"""Enterprise RAG Intelligence Platform - FastAPI Application."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.config import get_settings
from app.retrieval.sql_retriever import SQLRetriever
from app.retrieval.vector_store import VectorStore


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    SQLRetriever(settings)
    print("Enterprise RAG Platform initialized")
    yield


app = FastAPI(
    title="Enterprise RAG Intelligence Platform",
    description=(
        "Secure, context-aware RAG platform with RBAC, hybrid retrieval, "
        "and grounded response generation for enterprise data sources."
    ),
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1", tags=["RAG"])

from app.api.internal import router as internal_router
app.include_router(internal_router, tags=["Internal"])


@app.get("/")
async def root():
    return {
        "service": "Enterprise RAG Intelligence Platform",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
