"""Push notification Celery tasks — anomaly alerts + scheduled daily briefing."""

import asyncio
import logging

from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models.device_token import DeviceToken
from app.models.glucose import GlucoseReading
from app.models.user_settings import UserSettings
from app.utils.glucose_units import format_glucose
from app.workers.celery_app import celery_app

logger = get_task_logger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


@celery_app.task(name="check_glucose_anomaly")
def check_glucose_anomaly(user_id: int, glucose_mgdl: float, timestamp: str) -> None:
    """Check if a glucose reading is anomalous and send push if needed.

    Called after new glucose data is ingested (from CGM webhook or import).
    Triggers:
    - glucose > 250 mg/dL  → 高血糖预警
    - glucose < 54 mg/dL   → 低血糖预警
    - rapid rise > 3 mg/dL per 5 min (checked by caller)
    """
    db = SessionLocal()
    try:
        # Check user has active device tokens
        has_tokens = db.scalars(
            select(DeviceToken).where(
                DeviceToken.user_id == user_id,
                DeviceToken.is_active.is_(True),
            ).limit(1)
        ).first()

        if not has_tokens:
            return

        # Check intervention level — L1 only alerts on high risk
        settings = db.scalars(
            select(UserSettings).where(UserSettings.user_id == user_id)
        ).first()
        level = settings.intervention_level if settings else "L2"
        unit = settings.glucose_unit if settings else "mg_dl"
        g_str = format_glucose(glucose_mgdl, unit)

        title = ""
        body = ""
        push_data = {"type": "glucose_alert", "glucose_mgdl": glucose_mgdl}

        if glucose_mgdl > 250:
            title = "⚠️ 高血糖预警"
            body = f"当前血糖 {g_str}，明显偏高，建议活动或咨询医生。"
        elif glucose_mgdl < 54:
            title = "🚨 低血糖预警"
            body = f"当前血糖 {g_str}，请立即补充糖分！"
        elif glucose_mgdl > 180 and level in ("L2", "L3"):
            title = "📈 血糖偏高提醒"
            body = f"当前血糖 {g_str}，已超出目标范围，建议餐后散步 15 分钟。"
        elif glucose_mgdl < 70 and level in ("L2", "L3"):
            title = "📉 血糖偏低提醒"
            body = f"当前血糖 {g_str}，低于目标范围，注意补充碳水。"
        else:
            return  # No alert needed

        from app.services.push_service import send_push_to_user
        sent = _run_async(send_push_to_user(user_id, title, body, push_data))
        logger.info("Glucose alert push sent to user %d: %d devices", user_id, sent)

    except Exception:
        logger.exception("check_glucose_anomaly failed for user %d", user_id)
    finally:
        db.close()


@celery_app.task(name="send_daily_briefing_push")
def send_daily_briefing_push() -> None:
    """Send morning daily briefing push to all users with active device tokens.

    Should be scheduled via Celery Beat at e.g. 08:00 every day.
    """
    db = SessionLocal()
    try:
        # Find all users with active device tokens
        user_ids = db.scalars(
            select(DeviceToken.user_id).where(DeviceToken.is_active.is_(True)).distinct()
        ).all()

        from app.services.agent_service import generate_daily_briefing
        from app.services.push_service import send_push_to_user

        for uid in user_ids:
            try:
                briefing = generate_daily_briefing(db, uid)
                if briefing is None:
                    continue

                status = briefing.get("glucose_status", {})
                label = status.get("label", "正常")
                tir = status.get("tir_24h")
                tir_text = f"，TIR {tir:.0f}%" if tir else ""

                title = "🌅 今日代谢天气"
                body = f"血糖状态：{label}{tir_text}。打开小捷查看今日计划。"

                _run_async(send_push_to_user(uid, title, body, {"type": "daily_briefing"}))
            except Exception:
                logger.exception("Daily briefing push failed for user %d", uid)

    finally:
        db.close()


@celery_app.task(name="send_rescue_push")
def send_rescue_push(user_id: int) -> None:
    """Send a rescue alert push when post-meal glucose spike is detected."""
    from app.services.push_service import send_push_to_user

    title = "🏃 餐后补救提醒"
    body = "检测到餐后血糖快速上升，建议立即步行 15 分钟。"
    _run_async(send_push_to_user(user_id, title, body, {"type": "rescue"}))
