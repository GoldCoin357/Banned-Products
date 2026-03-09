"""
Banned Products Detection System — FastAPI application entry point.

Startup sequence:
  1. Initialise the SQLite database.
  2. Schedule background jobs (CPSC sync, platform scans).
  3. Mount all API routers.
  4. Serve static dashboard files.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio

from .config import get_settings
from .database import init_db
from .routers import (
    recalls_router,
    listings_router,
    analytics_router,
    scan_router,
    esafe_router,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


# ---------------------------------------------------------------------------
# Lifespan context manager (startup / shutdown)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", settings.APP_NAME, settings.APP_VERSION)
    init_db()
    logger.info("Database initialised")

    # Kick off background scheduler
    scheduler_task = asyncio.create_task(_run_scheduler())

    yield

    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    logger.info("Application shutdown complete")


async def _run_scheduler():
    """
    Simple async scheduler that periodically:
      - Re-syncs CPSC recall data.
      - Triggers scans across all platforms.
    """
    from .database import SessionLocal
    from .services.cpsc_service import fetch_cpsc_recalls

    cpsc_interval = settings.CPSC_REFRESH_INTERVAL_HOURS * 3600
    scan_interval = settings.SCRAPE_INTERVAL_MINUTES * 60

    cpsc_countdown = 0        # run immediately on startup
    scan_countdown = 300      # first scan 5 min after startup

    while True:
        try:
            await asyncio.sleep(60)  # tick every minute
            cpsc_countdown -= 60
            scan_countdown -= 60

            if cpsc_countdown <= 0:
                logger.info("Scheduler: triggering CPSC sync")
                db = SessionLocal()
                try:
                    stats = await fetch_cpsc_recalls(db)
                    logger.info("CPSC sync complete: %s", stats)
                finally:
                    db.close()
                cpsc_countdown = cpsc_interval

            if scan_countdown <= 0:
                logger.info("Scheduler: triggering platform scans")
                await _scheduled_scan()
                scan_countdown = scan_interval

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Scheduler error: %s", exc, exc_info=True)


async def _scheduled_scan():
    """Run scans for the top active recalls across all platforms."""
    from .database import SessionLocal
    from .models.recall import RecalledProduct
    from .services.scan_service import run_all_platforms_scan

    db = SessionLocal()
    try:
        # Scan the 10 most recently updated recalls
        recalls = (
            db.query(RecalledProduct)
            .filter(RecalledProduct.is_active == True)
            .order_by(RecalledProduct.updated_at.desc())
            .limit(10)
            .all()
        )
        for recall in recalls:
            await run_all_platforms_scan(
                db=db,
                recall=recall,
                max_results=25,
                auto_submit_esafe=False,
            )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Automated detection of recalled and banned products listed on C2C marketplaces. "
        "Integrates with the CPSC eSAFE Rapid reporting tool."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routers
app.include_router(recalls_router)
app.include_router(listings_router)
app.include_router(analytics_router)
app.include_router(scan_router)
app.include_router(esafe_router)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/health", tags=["system"])
def health_check():
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
    }


# ---------------------------------------------------------------------------
# Static dashboard files
# ---------------------------------------------------------------------------

import os
FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")

if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND_DIR, "assets")), name="static")
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")

    @app.get("/", include_in_schema=False)
    def serve_dashboard():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    @app.get("/{path:path}", include_in_schema=False)
    def serve_spa(path: str):
        file_path = os.path.join(FRONTEND_DIR, path)
        if os.path.isfile(file_path):
            return FileResponse(file_path)
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))
