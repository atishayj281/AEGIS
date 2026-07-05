from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import __version__
from app.api.routes import router
from app.api.admin import admin_router
from app.api.platform_admin import router as platform_admin_router
from app.config import get_settings
from app.retrieval.vector_store import VectorStore
from app.security.headers import SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
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

# Security headers — registered first so they apply to every response,
# including CORS pre-flight responses.
app.add_middleware(SecurityHeadersMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1", tags=["RAG"])
app.include_router(admin_router, prefix="/admin", tags=["Admin — User Provisioning"])
app.include_router(platform_admin_router, tags=["Platform Admin (superuser)"])





@app.get("/")
async def root():
    return {
        "service": "Enterprise RAG Intelligence Platform",
        "version": __version__,
        "docs": "/docs",
        "health": "/api/v1/health",
    }
