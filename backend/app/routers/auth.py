import logging
import re
import uuid
from collections import defaultdict
from pathlib import Path
from time import time

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.deps import get_db
from app.core.security import (
    create_token_pair,
    decode_token,
    hash_password,
    verify_password,
)
from app.core.token_blacklist import get_blacklist
from app.models.consent import Consent
from app.models.glucose import GlucoseReading
from app.models.user import User
from app.models.user_profile import UserProfile
from app.schemas.user import (
    AuthResponse,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SubjectInfo,
    SubjectLoginRequest,
    WxLoginRequest,
)
from app.services.activity_service import log_activity
from app.services.etl.glucose_etl import _parse_clarity_csv  # noqa: PLC2701

logger = logging.getLogger(__name__)

router = APIRouter()

# ── Simple in-memory rate limiter ────────────────────────────

_login_attempts: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(key: str) -> None:
    """Raise 429 if >N login attempts per minute from the same key."""
    now = time()
    window = 60.0
    attempts = _login_attempts[key]
    # Prune old entries
    _login_attempts[key] = [t for t in attempts if now - t < window]
    if len(_login_attempts[key]) >= settings.LOGIN_RATE_LIMIT_PER_MIN:
        raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.")
    _login_attempts[key].append(now)

# ── Resolve data directories ───────────────────────────────

_DATA_DIR = Path(__file__).resolve().parents[3] / "data"
_LIVER_DIR = Path(__file__).resolve().parents[3] / "fatty_liver_data_raw"


def _discover_subjects() -> list[SubjectInfo]:
    """Scan filesystem for available SC / Liver subjects."""
    subjects: list[SubjectInfo] = []

    # SC subjects — one Clarity CSV per subject
    glucose_dir = _DATA_DIR / "glucose"
    if glucose_dir.is_dir():
        for f in sorted(glucose_dir.glob("Clarity_Export_SC*.csv")):
            m = re.search(r"SC\d+", f.name)
            if m:
                subjects.append(
                    SubjectInfo(
                        subject_id=m.group(),
                        cohort="cgm",
                        has_meals=True,
                        has_glucose=True,
                    )
                )

    # Liver subjects — xls files in 监测数据
    monitor_dir = _LIVER_DIR / "监测数据"
    if monitor_dir.is_dir():
        seen: set[str] = set()
        for f in sorted(monitor_dir.iterdir()):
            m = re.search(r"Liver-\d+", f.name)
            if m and m.group() not in seen:
                seen.add(m.group())
                subjects.append(
                    SubjectInfo(
                        subject_id=m.group(),
                        cohort="liver",
                        has_meals=False,
                        has_glucose=True,
                    )
                )

    return subjects


# ── Subject listing ──────────────────────────────────────────


@router.get("/subjects", response_model=list[SubjectInfo])
def list_subjects():
    """Return all available study subjects from the data directory."""
    return _discover_subjects()


# ── Subject login (no password) ──────────────────────────────


@router.post("/login-subject", response_model=AuthResponse)
def login_subject(payload: SubjectLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Log in as a study subject.  Creates user + profile on first login."""
    sid = payload.subject_id.strip()

    # Validate subject exists on disk
    known = {s.subject_id: s for s in _discover_subjects()}
    if sid not in known:
        raise HTTPException(status_code=404, detail=f"Subject {sid} not found")

    info = known[sid]

    # Find existing profile
    profile = db.execute(
        select(UserProfile).where(UserProfile.subject_id == sid)
    ).scalars().first()

    if profile and profile.user_id:
        # Already has a linked user → auto-import if needed, then return token
        _auto_import_glucose(db, profile.user_id, sid, info.cohort)
        log_activity(db, profile.user_id, "login_subject", {"subject_id": sid},
                     ip_address=request.client.host if request.client else None,
                     user_agent=request.headers.get("user-agent"))
        tokens = create_token_pair(str(profile.user_id))
        return AuthResponse(**tokens, expires_in=settings.JWT_ACCESS_EXPIRES_MIN * 60)

    # Create user (use subject_id as phone placeholder)
    phone_placeholder = f"{sid.lower()}_subject"
    user = db.execute(select(User).where(User.phone == phone_placeholder)).scalars().first()
    if not user:
        user = User(
            phone=phone_placeholder,
            username=sid,
            password=hash_password(uuid.uuid4().hex),  # random password
        )
        db.add(user)
        db.flush()

        consent = Consent(
            user_id=user.id,
            allow_ai_chat=True,
            allow_data_upload=True,
        )
        db.add(consent)

    # Create or link profile
    if not profile:
        profile = UserProfile(
            subject_id=sid,
            user_id=user.id,
            cohort=info.cohort,
        )
        db.add(profile)
    else:
        profile.user_id = user.id

    db.commit()

    # Auto-import glucose data for the subject on first login
    _auto_import_glucose(db, user.id, sid, info.cohort)

    log_activity(db, user.id, "login_subject", {"subject_id": sid, "first_login": True},
                 ip_address=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent"))
    tokens = create_token_pair(str(user.id))
    return AuthResponse(**tokens, expires_in=settings.JWT_ACCESS_EXPIRES_MIN * 60)


def _auto_import_glucose(db: Session, user_id: int, subject_id: str, cohort: str) -> None:
    """If the user has no glucose data, import from the subject's CSV."""
    count = db.execute(
        select(func.count()).select_from(GlucoseReading).where(GlucoseReading.user_id == user_id)
    ).scalar() or 0
    if count > 0:
        return  # Already has data

    if cohort == "cgm":
        csv_path = _DATA_DIR / "glucose" / f"Clarity_Export_{subject_id}.csv"
        if csv_path.is_file():
            rows = _parse_clarity_csv(csv_path)
            for row in rows:
                db.add(GlucoseReading(
                    user_id=user_id,
                    ts=row["ts"],
                    glucose_mgdl=row["glucose_mgdl"],
                    source="auto_import",
                    meta={},
                ))
            db.commit()
            logger.info("Auto-imported %d glucose readings for %s", len(rows), subject_id)


# ── Classic phone / password ─────────────────────────────────


@router.post("/signup", response_model=AuthResponse)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    _check_rate_limit(f"signup:{payload.phone}")

    existing = db.execute(select(User).where(User.phone == payload.phone)).scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="该手机号已注册，请直接登录")

    user = User(phone=payload.phone, username=payload.username, password=hash_password(payload.password))
    db.add(user)
    db.flush()

    consent = Consent(user_id=user.id, allow_ai_chat=False, allow_data_upload=True)
    db.add(consent)

    # 注册时一并写入个人资料（性别/年龄/身高/体重），用 phone 作为 subject_id 占位以满足唯一约束
    if any(v is not None for v in (payload.sex, payload.age, payload.height_cm, payload.weight_kg)):
        profile = UserProfile(
            user_id=user.id,
            subject_id=f"phone_{user.id}",
            sex=payload.sex,
            age=payload.age,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            cohort="phone",
        )
        db.add(profile)

    db.commit()
    db.refresh(user)

    logger.info("New user signed up: %s", user.phone)
    log_activity(db, user.id, "signup", {"phone": user.phone},
                 ip_address=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent"))
    tokens = create_token_pair(str(user.id))
    return AuthResponse(**tokens, expires_in=settings.JWT_ACCESS_EXPIRES_MIN * 60)


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    _check_rate_limit(f"login:{payload.phone}")

    user = db.execute(select(User).where(User.phone == payload.phone)).scalars().first()
    if user is None or not verify_password(payload.password, user.password):
        raise HTTPException(status_code=401, detail="手机号或密码错误")

    logger.info("User logged in: %s", user.phone)
    log_activity(db, user.id, "login", {"phone": user.phone},
                 ip_address=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent"))
    tokens = create_token_pair(str(user.id))
    return AuthResponse(**tokens, expires_in=settings.JWT_ACCESS_EXPIRES_MIN * 60)


@router.post("/refresh", response_model=AuthResponse)
def refresh_token(payload: RefreshRequest):
    """Exchange a valid refresh token for a new access + refresh token pair."""
    try:
        data = decode_token(payload.refresh_token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token") from exc

    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Not a refresh token")

    # Check if old refresh token was revoked
    jti = data.get("jti")
    if jti and get_blacklist().is_blacklisted(jti):
        raise HTTPException(status_code=401, detail="Refresh token revoked")

    # Blacklist old refresh token to prevent reuse
    if jti:
        get_blacklist().add(jti, data.get("exp", 0))

    user_id = data["sub"]
    tokens = create_token_pair(user_id)
    return AuthResponse(**tokens, expires_in=settings.JWT_ACCESS_EXPIRES_MIN * 60)


# ── WeChat Mini Program login ────────────────────────────────


@router.post("/wx-login", response_model=AuthResponse)
def wx_login(payload: WxLoginRequest, request: Request, db: Session = Depends(get_db)):
    """Exchange WeChat login code for JWT tokens.

    Calls WeChat jscode2session API to get openid, then finds or
    creates a local user bound to that openid.
    In dev mode (WX_SECRET not set), uses code as a mock openid.
    """
    code = payload.code

    if settings.WX_APPID and settings.WX_SECRET:
        # ── Production: call WeChat API ──
        import httpx  # noqa: PLC0415

        wx_url = "https://api.weixin.qq.com/sns/jscode2session"
        params = {
            "appid": settings.WX_APPID,
            "secret": settings.WX_SECRET,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        with httpx.Client(timeout=10) as client:
            resp = client.get(wx_url, params=params)
        data = resp.json()
        openid = data.get("openid")
        if not openid:
            logger.warning("WeChat login failed: %s", data)
            raise HTTPException(status_code=401, detail="WeChat login failed")
    else:
        # ── Dev mode: use code hash as mock openid ──
        import hashlib  # noqa: PLC0415
        openid = "dev_" + hashlib.sha256(code.encode()).hexdigest()[:16]
        logger.info("WeChat dev login: mock openid=%s", openid)

    # Find or create user by openid (stored as phone placeholder)
    phone_placeholder = f"wx_{openid}"
    user = db.execute(select(User).where(User.phone == phone_placeholder)).scalars().first()
    if not user:
        user = User(
            phone=phone_placeholder,
            username=f"wx_{openid[:8]}",
            password=hash_password(uuid.uuid4().hex),
        )
        db.add(user)
        db.flush()
        consent = Consent(
            user_id=user.id,
            allow_ai_chat=True,
            allow_data_upload=True,
        )
        db.add(consent)
        db.commit()
        logger.info("New WeChat user created: openid=%s", openid[:8])

    log_activity(db, user.id, "wx_login", {"openid_prefix": openid[:8]},
                 ip_address=request.client.host if request.client else None,
                 user_agent=request.headers.get("user-agent"))
    tokens = create_token_pair(str(user.id))
    return AuthResponse(**tokens, expires_in=settings.JWT_ACCESS_EXPIRES_MIN * 60)


@router.post("/logout")
def logout(authorization: str = Header(default="")):
    """Revoke current access token (and optionally refresh token)."""
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    if token:
        try:
            payload = decode_token(token)
            jti = payload.get("jti")
            if jti:
                get_blacklist().add(jti, payload.get("exp", 0))
        except Exception:  # noqa: BLE001
            pass  # Token already expired or invalid — that's fine
    return {"ok": True}
