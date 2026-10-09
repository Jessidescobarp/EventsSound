from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from eventssound.application.health import check_database

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Never touches the database."""
    return {"status": "ok"}


@router.get("/health/db")
def health_db(request: Request) -> JSONResponse:
    """Readiness probe. Reports database reachability without leaking details."""
    if check_database(request.app.state.database_health):
        return JSONResponse({"status": "ok", "database": "ok"})
    return JSONResponse({"status": "degraded", "database": "unavailable"}, status_code=503)
