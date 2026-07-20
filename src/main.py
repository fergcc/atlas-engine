"""
Atlas Engine — FastAPI application.

Extensible backend that implements the territorial-industrial prospective
methodology from the Atlas. Supports:
  - Batch pipeline execution (data ingestion → econometrics → export)
  - On-demand analysis (CGV, territorial indicators, custom econometrics)
  - LLM services (DeepSeek for classification, extraction, narratives)
  - Search services (SearchAPI for research)

Two modes: development (mocks + test keys) and production (vault + real APIs).
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config import settings
from src.database import init_db
from src.api.routes import data, analysis, llm, search, admin, adapters


db_connection: object = None


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    global db_connection
    db_connection = init_db(settings.db_path)
    yield
    if db_connection:
        db_connection.close()


app = FastAPI(
    title="Atlas Engine",
    description="Engine for the Atlas Prospectivo Territorial-Industrial",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data.router, prefix="/api/v1")
app.include_router(analysis.router, prefix="/api/v1")
app.include_router(llm.router, prefix="/api/v1")
app.include_router(search.router, prefix="/api/v1")
app.include_router(admin.router, prefix="/api/v1")
app.include_router(adapters.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health():
    from src.adapters.registry import list_countries
    return {
        "status": "ok",
        "engine_env": settings.engine_env,
        "use_mocks": settings.use_mocks,
        "db_connected": db_connection is not None,
        "version": "0.1.0",
        "countries_available": list_countries(),
    }


@app.get("/")
async def root():
    return {
        "service": "Atlas Engine",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/api/v1/health",
    }
