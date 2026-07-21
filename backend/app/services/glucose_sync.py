"""Periodic sync: glucose_timeseries → glucose_readings.

The external CGM middleware (WeiTai) writes directly to `glucose_timeseries`.
Our API reads from `glucose_readings`. This background task keeps them in sync.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.core.config import settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

SYNC_INTERVAL_SECONDS = 60  # run every minute


def _sync_once() -> int:
    """Copy new rows from glucose_timeseries → glucose_readings.

    Matches user_phone → user_account.phone to resolve user_id.
    Skips rows already present (dedup by user_id + ts + source).
    Returns the number of newly inserted rows.
    """
    db = SessionLocal()
    try:
        result = db.execute(text("""
            INSERT INTO glucose_readings (user_id, ts, glucose_mgdl, source, meta)
            SELECT u.id,
                   gt.device_time,
                   gt.event_data::integer,
                   'cgm_device_api',
                   json_build_object(
                       'device_sn', gt.device_sn,
                       'phone', gt.user_phone,
                       'synced', true
                   )
            FROM glucose_timeseries gt
            JOIN user_account u ON u.phone = gt.user_phone
            WHERE gt.event_data BETWEEN 20 AND 600
              AND NOT EXISTS (
                  SELECT 1 FROM glucose_readings gr
                  WHERE gr.user_id = u.id
                    AND gr.ts = gt.device_time
                    AND gr.source = 'cgm_device_api'
              )
            ORDER BY gt.device_time
        """))
        count = result.rowcount
        db.commit()
        return count
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def start_glucose_sync_loop() -> None:
    """Run the sync loop forever, logging errors but never crashing."""
    if not settings.DATABASE_URL.startswith(("postgresql://", "postgresql+")):
        logger.info("Glucose sync loop skipped for non-PostgreSQL database")
        return
    logger.info("Glucose sync loop started (interval=%ds)", SYNC_INTERVAL_SECONDS)
    while True:
        try:
            count = _sync_once()
            if count > 0:
                logger.info("Glucose sync: inserted %d new readings", count)
        except Exception:
            logger.exception("Glucose sync error")
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)
