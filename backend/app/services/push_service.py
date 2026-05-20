"""APNs push notification service using HTTP/2 via httpx."""

import json
import logging
import time
from pathlib import Path

import httpx
import jwt

from app.core.config import settings

logger = logging.getLogger(__name__)

APNS_SANDBOX_HOST = "https://api.sandbox.push.apple.com"
APNS_PRODUCTION_HOST = "https://api.push.apple.com"

_cached_token: dict | None = None


def _get_apns_jwt() -> str:
    """Create or reuse an APNs JWT (valid for ~50 minutes, refresh at 45)."""
    global _cached_token
    now = int(time.time())

    if _cached_token and now - _cached_token["issued_at"] < 2700:
        return _cached_token["token"]

    key_path = Path(settings.APNS_KEY_PATH)
    if not key_path.exists():
        raise FileNotFoundError(f"APNs key file not found: {key_path}")

    private_key = key_path.read_text()
    payload = {"iss": settings.APNS_TEAM_ID, "iat": now}
    token = jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": settings.APNS_KEY_ID})

    _cached_token = {"token": token, "issued_at": now}
    return token


def _apns_host() -> str:
    return APNS_SANDBOX_HOST if settings.APNS_USE_SANDBOX else APNS_PRODUCTION_HOST


async def send_push(device_token: str, title: str, body: str, data: dict | None = None) -> bool:
    """Send a single push notification via APNs HTTP/2.

    Returns True on success, False on failure.
    """
    try:
        token = _get_apns_jwt()
    except (FileNotFoundError, Exception) as e:
        logger.error("APNs JWT creation failed: %s", e)
        return False

    url = f"{_apns_host()}/3/device/{device_token}"
    headers = {
        "authorization": f"bearer {token}",
        "apns-topic": settings.APNS_BUNDLE_ID,
        "apns-push-type": "alert",
        "apns-priority": "10",
    }
    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        }
    }
    if data:
        payload["data"] = data

    try:
        async with httpx.AsyncClient(http2=True, timeout=10) as client:
            resp = await client.post(url, headers=headers, content=json.dumps(payload))
            if resp.status_code == 200:
                return True
            elif resp.status_code == 410:
                logger.info("APNs token expired/invalid, should deactivate: %s", device_token[:20])
                return False
            else:
                logger.warning("APNs error %d: %s", resp.status_code, resp.text)
                return False
    except Exception:
        logger.exception("APNs request failed for token %s", device_token[:20])
        return False


async def send_push_to_user(user_id: int, title: str, body: str, data: dict | None = None) -> int:
    """Send push to all active devices of a user. Returns count of successful sends."""
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.device_token import DeviceToken

    db = SessionLocal()
    try:
        tokens = db.scalars(
            select(DeviceToken).where(DeviceToken.user_id == user_id, DeviceToken.is_active.is_(True))
        ).all()

        success_count = 0
        for dt in tokens:
            # Currently only APNs (iOS) remote push is wired up. Android clients
            # rely on local AlarmManager + foreground polling. If/when FCM is
            # configured, dispatch here based on dt.platform.
            if dt.platform != "ios":
                continue
            ok = await send_push(dt.token, title, body, data)
            if ok:
                success_count += 1
            else:
                # Deactivate invalid tokens (410 Gone)
                dt.is_active = False
                db.add(dt)

        db.commit()
        return success_count
    finally:
        db.close()
