#!/usr/bin/env python3
"""Local read-only dashboard API for Xjie server operations.

The browser cannot SSH into the ECS host directly. This helper binds to
127.0.0.1, reads SSH credentials from the workspace .env file, and exposes a
small JSON endpoint for the local development dashboard.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DEFAULT_PORT = 8791
SECTION_PREFIX = "__XJIE_SECTION__"

COUNT_TABLES = [
    "user_account",
    "conversations",
    "chat_messages",
    "meals",
    "meal_photos",
    "glucose_readings",
    "glucose_timeseries",
    "health_documents",
    "user_indicator_values",
    "omics_uploads",
    "medication",
    "elderly_checkin",
    "mood_logs",
    "exercise_logs",
    "llm_audit_logs",
    "literature",
    "feature_flags",
    "skills",
]


def find_workspace_root(start: Path) -> Path:
    """Find the shared workspace root that contains .env and both repos."""
    candidates = [start.resolve(), *start.resolve().parents]
    for candidate in candidates:
        if (
            (candidate / ".env").exists()
            and (candidate / "XJie_IOS").exists()
            and (candidate / "XJie_And").exists()
        ):
            return candidate
    return start.resolve()


def load_env(root: Path) -> dict[str, str]:
    env_path = root / ".env"
    values: dict[str, str] = {}
    if not env_path.exists():
        raise FileNotFoundError(f"Missing .env at {env_path}")
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def remote_script() -> str:
    counts = " ".join(COUNT_TABLES)
    return f"""#!/usr/bin/env bash
set +e
section() {{ printf '\\n{SECTION_PREFIX}%s\\n' "$1"; }}

section host
hostname
date -Is
uptime -p 2>/dev/null || uptime
uname -srmo

section disk
df -h / | awk 'NR==2 {{print $1 "|" $2 "|" $3 "|" $4 "|" $5 "|" $6}}'

section memory
free -m 2>/dev/null | awk 'NR==2 {{print $2 "|" $3 "|" $4 "|" $7}}'

section docker_ps
docker ps --format '{{{{json .}}}}'

section docker_stats
docker stats --no-stream --format '{{{{json .}}}}'

section docker_health
for name in $(docker ps --format '{{{{.Names}}}}'); do
  health=$(docker inspect "$name" --format '{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{else}}}}none{{{{end}}}}' 2>/dev/null)
  printf '%s|%s\\n' "$name" "$health"
done

section api_health
if command -v curl >/dev/null 2>&1; then
  curl -fsS --max-time 4 http://127.0.0.1:8000/healthz 2>&1
else
  docker exec xjie-api python - <<'PY' 2>&1
import json
import urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=4) as r:
        print(r.read().decode("utf-8"))
except Exception as exc:
    print(str(exc))
PY
fi

section db_tables
docker exec timescaledb sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select tablename from pg_tables where schemaname='"'"'public'"'"' order by tablename;"' 2>&1

section db_counts
for table in {counts}; do
  count=$(docker exec timescaledb sh -lc "PGPASSWORD=\\"\\$POSTGRES_PASSWORD\\" psql -U \\"\\$POSTGRES_USER\\" -d \\"\\$POSTGRES_DB\\" -Atc \\"select count(*) from $table;\\"" 2>/dev/null)
  printf '%s|%s\\n' "$table" "$count"
done

section migration
docker exec timescaledb sh -lc 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "select version_num from alembic_version limit 1;"' 2>&1
"""


def run_ssh(env_values: dict[str, str], timeout: int = 45) -> str:
    required = ["SSH_HOST", "SSH_USER", "SSH_PASS"]
    missing = [key for key in required if not env_values.get(key)]
    if missing:
        raise RuntimeError(f"Missing required .env keys: {', '.join(missing)}")

    sshpass = shutil.which("sshpass")
    ssh = shutil.which("ssh")
    if not ssh:
        raise RuntimeError("ssh command is not available")
    if not sshpass:
        raise RuntimeError("sshpass is required for password-based SSH access")

    command = [
        sshpass,
        "-e",
        ssh,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/tmp/xjie_dashboard_known_hosts",
        "-o",
        "ConnectTimeout=12",
        f"{env_values['SSH_USER']}@{env_values['SSH_HOST']}",
        "bash -s",
    ]
    proc_env = os.environ.copy()
    proc_env["SSHPASS"] = env_values["SSH_PASS"]
    proc = subprocess.run(
        command,
        input=remote_script(),
        text=True,
        capture_output=True,
        env=proc_env,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"SSH command failed with code {proc.returncode}: {detail}")
    return proc.stdout


def split_sections(output: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for raw in output.splitlines():
        if raw.startswith(SECTION_PREFIX):
            current = raw.removeprefix(SECTION_PREFIX).strip()
            sections[current] = []
            continue
        if current:
            sections[current].append(raw.rstrip())
    return sections


def parse_json_lines(lines: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except json.JSONDecodeError:
            items.append({"raw": line})
    return items


def parse_snapshot(output: str, env_values: dict[str, str]) -> dict[str, Any]:
    sections = split_sections(output)
    host_lines = sections.get("host", [])
    disk_line = next((line for line in sections.get("disk", []) if line.strip()), "")
    disk_parts = disk_line.split("|") if disk_line else []
    memory_line = next((line for line in sections.get("memory", []) if line.strip()), "")
    memory_parts = memory_line.split("|") if memory_line else []

    containers = parse_json_lines(sections.get("docker_ps", []))
    stats_by_name = {
        item.get("Name") or item.get("Name".lower()): item
        for item in parse_json_lines(sections.get("docker_stats", []))
        if isinstance(item, dict)
    }
    health_by_name: dict[str, str] = {}
    for line in sections.get("docker_health", []):
        if "|" in line:
            name, health = line.split("|", 1)
            health_by_name[name] = health

    merged_containers: list[dict[str, Any]] = []
    for container in containers:
        name = container.get("Names") or container.get("Name") or container.get("raw", "")
        stats = stats_by_name.get(name, {})
        merged_containers.append(
            {
                "name": name,
                "image": container.get("Image", ""),
                "status": container.get("Status", ""),
                "ports": container.get("Ports", ""),
                "health": health_by_name.get(name, "unknown"),
                "cpu": stats.get("CPUPerc", ""),
                "memory": stats.get("MemUsage", ""),
                "net_io": stats.get("NetIO", ""),
                "block_io": stats.get("BlockIO", ""),
            }
        )

    counts: dict[str, int | None] = {}
    for line in sections.get("db_counts", []):
        if "|" not in line:
            continue
        table, value = line.split("|", 1)
        try:
            counts[table] = int(value)
        except ValueError:
            counts[table] = None

    tables = [line for line in sections.get("db_tables", []) if line and not line.startswith("psql:")]
    api_health = "\n".join(line for line in sections.get("api_health", []) if line).strip()
    migration = next((line for line in sections.get("migration", []) if line and not line.startswith("psql:")), "")

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "live-ssh",
        "ssh_host": env_values.get("SSH_HOST", ""),
        "api_base_url": env_values.get("API_BASE_URL", ""),
        "host": {
            "hostname": host_lines[0] if len(host_lines) > 0 else "",
            "server_time": host_lines[1] if len(host_lines) > 1 else "",
            "uptime": host_lines[2] if len(host_lines) > 2 else "",
            "kernel": host_lines[3] if len(host_lines) > 3 else "",
        },
        "resources": {
            "disk": {
                "filesystem": disk_parts[0] if len(disk_parts) > 0 else "",
                "size": disk_parts[1] if len(disk_parts) > 1 else "",
                "used": disk_parts[2] if len(disk_parts) > 2 else "",
                "available": disk_parts[3] if len(disk_parts) > 3 else "",
                "used_percent": disk_parts[4] if len(disk_parts) > 4 else "",
                "mount": disk_parts[5] if len(disk_parts) > 5 else "",
            },
            "memory_mb": {
                "total": int(memory_parts[0]) if len(memory_parts) > 0 and memory_parts[0].isdigit() else None,
                "used": int(memory_parts[1]) if len(memory_parts) > 1 and memory_parts[1].isdigit() else None,
                "free": int(memory_parts[2]) if len(memory_parts) > 2 and memory_parts[2].isdigit() else None,
                "available": int(memory_parts[3]) if len(memory_parts) > 3 and memory_parts[3].isdigit() else None,
            },
        },
        "containers": merged_containers,
        "database": {
            "migration": migration,
            "table_count": len(tables),
            "tables": tables,
            "counts": counts,
        },
        "health": {
            "api_health": api_health,
            "unhealthy_containers": [
                item["name"]
                for item in merged_containers
                if item.get("health") not in ("none", "healthy", "unknown")
            ],
        },
    }


def get_snapshot(root: Path) -> dict[str, Any]:
    env_values = load_env(root)
    output = run_ssh(env_values)
    return parse_snapshot(output, env_values)


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(data)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(data)


class DashboardHandler(BaseHTTPRequestHandler):
    root: Path

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/health":
            json_response(self, 200, {"ok": True, "service": "xjie-dashboard-api"})
            return
        if path == "/api/server/snapshot":
            try:
                json_response(self, 200, get_snapshot(self.root))
            except Exception as exc:  # noqa: BLE001
                json_response(
                    self,
                    500,
                    {
                        "ok": False,
                        "generated_at": datetime.now(timezone.utc).isoformat(),
                        "error": str(exc),
                    },
                )
            return
        json_response(self, 404, {"ok": False, "error": "Not found"})

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Xjie dashboard API.")
    parser.add_argument("--root", type=Path, default=None, help="Workspace root containing .env")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host; keep 127.0.0.1 for safety")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Bind port")
    parser.add_argument("--once", action="store_true", help="Print one live JSON snapshot and exit")
    args = parser.parse_args()

    root = find_workspace_root(args.root or Path.cwd())
    if args.once:
        print(json.dumps(get_snapshot(root), ensure_ascii=False, indent=2))
        return 0

    DashboardHandler.root = root
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"Xjie dashboard API listening on http://{args.host}:{args.port}")
    print(f"Workspace root: {root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard API")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
