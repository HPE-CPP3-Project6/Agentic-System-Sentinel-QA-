"""
main.py
-------
FastAPI application entry point for the Smart Task Manager.

Responsibilities:
    - Create / initialise the SQLite database tables on startup.
    - Register all API routers.
    - Configure CORS, global exception handlers, and OpenAPI metadata.
    - Expose a health-check endpoint.

Run the server (development):
    uvicorn main:app --reload --host 0.0.0.0 --port 8000

Interactive API docs:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config import settings
from database import Base, engine
from routers import auth_router, task_router


# ---------------------------------------------------------------------------
# Lifespan: runs once at startup and once at shutdown
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Create all database tables defined in models.py on application startup.
    In production, prefer Alembic migrations over `create_all`.
    """
    Base.metadata.create_all(bind=engine)
    yield
    # Shutdown logic can be added here (e.g., close connection pools)


# ---------------------------------------------------------------------------
# FastAPI application instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Smart Task Manager API",
    description=(
        "Production-ready Task Manager backend with JWT authentication, "
        "soft-delete, and immutable audit logging."
    ),
    version="1.0.0",
    lifespan=lifespan,
    # Restrict OpenAPI docs in production by setting docs_url=None
    docs_url="/docs",
    redoc_url="/redoc",
)


# ---------------------------------------------------------------------------
# CORS Middleware
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Global exception handler – prevent raw tracebacks leaking to clients
# ---------------------------------------------------------------------------
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catches any unhandled exception and returns a safe 500 response.
    Raw stack traces are never exposed to the client (security best practice).
    """
    # In production, log `exc` to your observability platform here
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal server error occurred. Please try again later."},
    )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router.router)
app.include_router(task_router.router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health", tags=["System"], summary="Health check")
def health_check() -> dict:
    """Returns 200 OK if the service is running."""
    return {"status": "healthy", "service": "Smart Task Manager API"}


# ---------------------------------------------------------------------------
# Developer entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
