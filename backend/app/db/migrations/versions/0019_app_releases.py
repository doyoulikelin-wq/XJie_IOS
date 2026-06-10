"""Add mobile app release configuration.

Revision ID: 0019_app_releases
Revises: 0018_family_mode
Create Date: 2026-06-11
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0019_app_releases"
down_revision = "0018_family_mode"
branch_labels = None
depends_on = None


DEFAULT_RELEASES = [
    {
        "platform": "ios",
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
    {
        "platform": "android",
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
]


def _seed_defaults() -> None:
    bind = op.get_bind()
    stmt = sa.text(
        """
        INSERT INTO app_releases (
            platform, latest_version, latest_build, min_supported_build, force_update,
            title, message, changelog, download_url, store_url, sha256
        ) VALUES (
            :platform, :latest_version, :latest_build, :min_supported_build, :force_update,
            :title, :message, :changelog, :download_url, :store_url, :sha256
        )
        ON CONFLICT (platform) DO NOTHING
        """
    )
    for release in DEFAULT_RELEASES:
        bind.execute(stmt, release)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_releases" in inspector.get_table_names():
        _seed_defaults()
        return

    op.create_table(
        "app_releases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("latest_version", sa.String(length=32), nullable=False),
        sa.Column("latest_build", sa.Integer(), nullable=False),
        sa.Column("min_supported_build", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("force_update", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("title", sa.String(length=120), nullable=False, server_default="发现新版本"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("changelog", sa.Text(), nullable=False, server_default=""),
        sa.Column("download_url", sa.String(length=512), nullable=True),
        sa.Column("store_url", sa.String(length=512), nullable=True),
        sa.Column("sha256", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("platform", name="uq_app_releases_platform"),
    )
    op.create_index("ix_app_releases_platform", "app_releases", ["platform"])

    releases = sa.table(
        "app_releases",
        sa.column("platform", sa.String),
        sa.column("latest_version", sa.String),
        sa.column("latest_build", sa.Integer),
        sa.column("min_supported_build", sa.Integer),
        sa.column("force_update", sa.Boolean),
        sa.column("title", sa.String),
        sa.column("message", sa.Text),
        sa.column("changelog", sa.Text),
        sa.column("download_url", sa.String),
        sa.column("store_url", sa.String),
        sa.column("sha256", sa.String),
    )
    op.bulk_insert(releases, DEFAULT_RELEASES)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_releases" not in inspector.get_table_names():
        return
    op.drop_index("ix_app_releases_platform", table_name="app_releases")
    op.drop_table("app_releases")
