"""Public mobile app version check endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.models.app_release import AppRelease
from app.schemas.app_release import AppUpdateCheckOut

router = APIRouter()


DEFAULT_RELEASES: dict[str, dict] = {
    "ios": {
        "latest_version": "1.0",
        "latest_build": 6,
        "min_supported_build": 1,
        "force_update": False,
        "title": "发现小捷新版本",
        "message": "请前往 TestFlight 或 App Store 更新，获得最新功能和修复。",
        "changelog": "版本更新与稳定性改进。",
        "download_url": "https://testflight.apple.com",
        "store_url": "https://testflight.apple.com",
        "sha256": None,
    },
    "android": {
        "latest_version": "1.0",
        "latest_build": 1,
        "min_supported_build": 1,
        "force_update": False,
        "title": "发现小捷新版本",
        "message": "请下载并安装最新 APK，获得最新功能和修复。",
        "changelog": "版本更新与稳定性改进。",
        "download_url": "https://www.jianjieaitech.com/download/Xjie_latest.apk",
        "store_url": "https://www.jianjieaitech.com/download/Xjie_latest.apk",
        "sha256": None,
    },
}


def _release_payload(platform: str, db: Session) -> dict:
    release = db.execute(
        select(AppRelease).where(AppRelease.platform == platform)
    ).scalar_one_or_none()
    if release:
        return {
            "latest_version": release.latest_version,
            "latest_build": release.latest_build,
            "min_supported_build": release.min_supported_build,
            "force_update": release.force_update,
            "title": release.title,
            "message": release.message,
            "changelog": release.changelog,
            "download_url": release.download_url,
            "store_url": release.store_url,
            "sha256": release.sha256,
            "updated_at": release.updated_at,
        }
    return DEFAULT_RELEASES[platform] | {"updated_at": None}


@router.get("", response_model=AppUpdateCheckOut)
@router.get("/", response_model=AppUpdateCheckOut)
def check_app_version(
    platform: str = Query(..., pattern="^(ios|android)$"),
    version: str | None = Query(default=None),
    build: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
) -> AppUpdateCheckOut:
    platform = platform.lower().strip()
    if platform not in DEFAULT_RELEASES:
        raise HTTPException(status_code=400, detail="Unsupported platform")

    data = _release_payload(platform, db)
    latest_build = int(data["latest_build"])
    min_supported_build = int(data["min_supported_build"])
    current_build = int(build) if build else None
    update_available = current_build is not None and current_build < latest_build
    required = current_build is not None and current_build < min_supported_build
    force_update = bool(data["force_update"]) or required

    return AppUpdateCheckOut(
        platform=platform,  # type: ignore[arg-type]
        current_version=version,
        current_build=current_build,
        latest_version=data["latest_version"],
        latest_build=latest_build,
        min_supported_build=min_supported_build,
        update_available=update_available,
        required=required,
        force_update=force_update,
        title=data["title"],
        message=data["message"],
        changelog=data["changelog"],
        download_url=data.get("download_url"),
        store_url=data.get("store_url"),
        sha256=data.get("sha256"),
        updated_at=data.get("updated_at"),
    )
