from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("metabodash", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "Asia/Shanghai"
celery_app.autodiscover_tasks(
    [
        "app.workers.tasks",
        "app.workers.push_tasks",
        "app.workers.literature_tasks",
        "app.workers.health_score_tasks",
        "app.workers.report_ocr_tasks",
        "app.workers.dietary_tasks",
    ]
)

# Scheduled tasks
celery_app.conf.beat_schedule = {
    "daily-briefing-push": {
        "task": "send_daily_briefing_push",
        "schedule": crontab(hour=8, minute=0),  # 每天早上8点
    },
    "weekly-omics-literature-ingest": {
        "task": "weekly_omics_literature_ingest",
        "schedule": crontab(hour=3, minute=0, day_of_week=1),  # 每周一 03:00
    },
    "health-report-score-job-sweep": {
        # Redis delivery is only a wake-up. The database job/lease is the
        # authority and this sweep reclaims work after broker or worker loss.
        "task": "process_health_report_score_jobs",
        "schedule": 30.0,
    },
    "health-report-ocr-workflow-sweep": {
        # OCR claims are leased in PostgreSQL; periodic discovery recovers work
        # even when a broker wake-up is lost.
        "task": "process_health_report_ocr_workflows",
        "schedule": 15.0,
    },
    "dietary-day-completion-sweep": {
        # Each row stores its timezone-derived next-day 04:00 UTC instant.
        # PostgreSQL SKIP LOCKED makes overlapping Beat deliveries harmless.
        "task": "process_due_dietary_days",
        "schedule": 60.0,
    },
}
