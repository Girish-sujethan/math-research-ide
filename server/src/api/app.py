"""FastAPI application factory."""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from src.api.routers import (
    agent,
    chat,
    concepts,
    discoveries,
    paper_discovery,
    papers,
    relationships,
    research,
    search,
    upload,
    verify,
)
from src.api.routers.agents import fact_check as fact_check_agent
from src.api.routers.agents import matlab as python_visual_agent
from src.config import settings
from src.db.sqlite.models import Concept, ConceptRelationship
from src.db.sqlite.session import get_session, init_db
from src.model.graphs.checkpointer import get_checkpointer
from src.model.graphs.discovery_graph import build_discovery_graph
from src.model.graphs.ingestion_graph import build_ingestion_graph
from src.model.graphs.paper_discovery_graph import build_paper_discovery_graph
from src.model.graphs.research_graph import build_research_graph

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit])


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: create DB tables and compile LangGraph pipelines."""
    if int(os.environ.get("WEB_CONCURRENCY", "1")) > 1:
        logger.error(
            "HEAVEN requires a single worker — sessions and running_threads are "
            "in-memory per-process. WEB_CONCURRENCY=%s will cause state divergence "
            "across workers. Set --workers 1 or migrate to persistent state first.",
            os.environ.get("WEB_CONCURRENCY"),
        )

    logger.info("HEAVEN startup: initialising database")
    init_db()

    logger.info("HEAVEN startup: compiling LangGraph pipelines")
    checkpointer = get_checkpointer()
    app.state.ingestion_graph = build_ingestion_graph(checkpointer)
    app.state.discovery_graph = build_discovery_graph(checkpointer)
    app.state.running_threads = set()  # {thread_id} — status cache only
    app.state.thread_metadata = {}  # {thread_id: {"paper_id": ..., "error": ...}}
    app.state.sessions = {}  # chat session history {session_id: [messages]}
    app.state.research_threads = set()  # {job_id} — in-flight research jobs
    app.state.research_metadata = {}  # {job_id: {"error": ...}}
    app.state.research_graph = build_research_graph(
        checkpointer=checkpointer,
        ingestion_graph=app.state.ingestion_graph,
        running_threads=app.state.running_threads,
        thread_metadata=app.state.thread_metadata,
    )
    app.state.paper_discovery_graph = build_paper_discovery_graph(checkpointer)
    app.state.paper_discovery_threads = set()
    app.state.paper_discovery_metadata = {}

    with get_session() as session:
        node_count = session.query(Concept).count()
        edge_count = session.query(ConceptRelationship).count()
    logger.info("HEAVEN ready — graph: %d concepts, %d relationships", node_count, edge_count)

    yield
    logger.info("HEAVEN shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="HEAVEN",
        description="AI-native research assistant for mathematicians",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS — configured via CORS_ORIGINS env var (comma-separated, default "*")
    origins = [o.strip() for o in settings.cors_origins.split(",")]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(papers.router)
    app.include_router(upload.router)
    app.include_router(concepts.router)
    app.include_router(discoveries.router)
    app.include_router(relationships.router)
    app.include_router(research.router)
    app.include_router(agent.router)
    app.include_router(search.router)
    app.include_router(chat.router)
    app.include_router(verify.router)
    app.include_router(python_visual_agent.router)
    app.include_router(fact_check_agent.router)
    app.include_router(paper_discovery.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        """Liveness check. Returns concept/relationship counts from SQLite."""
        with get_session() as session:
            node_count = session.query(Concept).count()
            edge_count = session.query(ConceptRelationship).count()
        return {
            "status": "ok",
            "graph_nodes": node_count,
            "graph_edges": edge_count,
        }

    return app


app = create_app()
