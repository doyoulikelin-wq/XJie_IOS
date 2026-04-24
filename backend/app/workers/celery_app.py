from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("metabodash", broker=settings.REDIS_URL, backend=settings.REDIS_URL)
celery_app.conf.task_serializer = "json"
celery_app.conf.result_serializer = "json"
celery_app.conf.accept_content = ["json"]
celery_app.conf.timezone = "Asia/Shanghai"
celery_app.autodiscover_tasks(["app.workers.tasks", "app.workers.push_tasks", "app.workers.literature_tasks"])

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
}
