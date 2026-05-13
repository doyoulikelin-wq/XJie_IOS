from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.core.config import settings
from app.core.logging import setup_logging
from app.core.middleware import RequestLoggingMiddleware
from app.db.base import Base
from app.db.session import engine
from app.routers import activity, admin, agent, auth, cgm, chat, dashboard, etl, exercise, glucose, health_data, health_reports, indicators_extra, literature, me, meals, mood, omics, push, users

_STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="MetaboDash API", version="0.2.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in settings.CORS_ORIGINS.split(",") if origin.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestLoggingMiddleware)

    @app.on_event("startup")
    def startup() -> None:
        Base.metadata.create_all(bind=engine)
        # Migrate: add 'feature' column to llm_audit_logs if missing
        with engine.connect() as conn:
            from sqlalchemy import text
            try:
                conn.execute(text(
                    "ALTER TABLE llm_audit_logs ADD COLUMN IF NOT EXISTS feature VARCHAR NOT NULL DEFAULT 'chat'"
                ))
                conn.commit()
            except Exception:
                conn.rollback()

        # Start background glucose sync from glucose_timeseries → glucose_readings
        import asyncio
        from app.services.glucose_sync import start_glucose_sync_loop
        asyncio.get_event_loop().create_task(start_glucose_sync_loop())

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(users.router, prefix="/api/users", tags=["users"])
    app.include_router(me.router, prefix="/api", tags=["users"])
    app.include_router(glucose.router, prefix="/api/glucose", tags=["glucose"])
    app.include_router(meals.router, prefix="/api/meals", tags=["meals"])
    app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
    app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
    app.include_router(etl.router, prefix="/api/etl", tags=["etl"])
    app.include_router(health_data.router, prefix="/api/health-data", tags=["health-data"])
    app.include_router(indicators_extra.router, prefix="/api/health-data", tags=["health-data"])
    app.include_router(exercise.router, prefix="/api/exercise", tags=["exercise"])
    app.include_router(health_reports.router, prefix="/api/health-reports", tags=["health-reports"])
    app.include_router(agent.router, prefix="/api/agent", tags=["agent"])
    app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
    app.include_router(cgm.router, prefix="/api/integrations/cgm", tags=["integrations-cgm"])
    app.include_router(omics.router, prefix="/api/omics", tags=["omics"])
    app.include_router(push.router, prefix="/api/push", tags=["push"])
    app.include_router(literature.router, prefix="/api/literature", tags=["literature"])
    app.include_router(mood.router, prefix="/api/mood", tags=["mood"])
    app.include_router(admin.router, prefix="/api/admin", tags=["admin"])

    # Public feature flags endpoint (authenticated, non-admin)
    from app.core.deps import get_current_user_id, get_db as _get_db
    from app.services.feature_service import get_all_flags
    from fastapi import Depends
    from sqlalchemy.orm import Session as _Session

    @app.get("/api/feature-flags", tags=["feature-flags"])
    def public_feature_flags(
        _user_id: int = Depends(get_current_user_id),
        db: _Session = Depends(_get_db),
    ):
        return {"flags": get_all_flags(db)}

    @app.get("/admin")
    def admin_page():
        return FileResponse(_STATIC_DIR / "admin.html", media_type="text/html")

    @app.get("/privacy")
    def privacy_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "static" / "privacy.html", media_type="text/html")

    @app.get("/")
    def marketing_page():
        return FileResponse(Path(__file__).resolve().parent.parent / "static" / "index.html", media_type="text/html")

    return app


app = create_app()
