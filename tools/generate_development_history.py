#!/usr/bin/env python3
"""Generate the Xjie cross-platform development history dashboard."""

from __future__ import annotations

import argparse
import html
import json
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TYPE_LABELS = {
    "feat": "功能",
    "fix": "修复",
    "docs": "文档",
    "chore": "维护",
    "refactor": "重构",
    "perf": "性能",
    "i18n": "国际化",
    "sync": "同步",
    "test": "测试",
    "style": "样式",
}

REPO_CONFIG = [
    {
        "key": "ios",
        "name": "iOS",
        "path": "XJie_IOS",
        "remote": "origin",
        "github": "https://github.com/doyoulikelin-wq/XJie_IOS",
    },
    {
        "key": "android",
        "name": "Android",
        "path": "XJie_And",
        "remote": "andro",
        "github": "https://github.com/doyoulikelin-wq/Xjie_andro",
    },
]


@dataclass
class RepoCommit:
    repo: str
    repo_key: str
    hash: str
    time: str
    author: str
    subject: str
    files: list[dict[str, str]] = field(default_factory=list)


def run(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=True)
    return result.stdout


def parse_type(subject: str) -> tuple[str, str, str]:
    prefix = subject.split(":", 1)[0] if ":" in subject else ""
    scope = ""
    kind = "other"
    if prefix:
        if "(" in prefix and prefix.endswith(")"):
            kind = prefix.split("(", 1)[0]
            scope = prefix.split("(", 1)[1][:-1]
        else:
            kind = prefix
    label = TYPE_LABELS.get(kind, "其他")
    return kind, label, scope


def infer_modules(repo_key: str, files: list[dict[str, str]], subject: str) -> list[str]:
    modules: set[str] = set()
    lowered = subject.lower()
    if repo_key == "ios":
        modules.add("iOS")
    if repo_key == "android":
        modules.add("Android")
    if "backend" in lowered:
        modules.add("Backend")
    if "readme" in lowered or "docs" in lowered:
        modules.add("Docs")
    for item in files:
        path = item["path"]
        lower = path.lower()
        if path.startswith("backend/"):
            modules.add("Backend")
        if path.startswith("Xjie/") or lower.endswith(".swift") or ".xcodeproj" in path:
            modules.add("iOS")
        if path.startswith("Android/") or lower.endswith(".kt") or "gradle" in lower:
            modules.add("Android")
        if path.startswith("docs/") or path.startswith("report/") or path.endswith(".md"):
            modules.add("Docs")
        if path.startswith("demo/"):
            modules.add("Web Demo")
    return sorted(modules)


def changed_files(repo: Path, commit_hash: str) -> list[dict[str, str]]:
    output = run(["git", "show", "--name-status", "--format=", "--no-renames", commit_hash], repo)
    files: list[dict[str, str]] = []
    for raw in output.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) == 1:
            files.append({"status": "", "path": parts[0]})
        else:
            files.append({"status": parts[0], "path": parts[-1]})
    return files


def repo_status(repo: Path) -> str:
    return run(["git", "status", "--short"], repo).strip()


def collect_repo(root: Path, cfg: dict[str, str]) -> tuple[list[RepoCommit], dict[str, Any]]:
    repo = root / cfg["path"]
    log = run(
        [
            "git",
            "log",
            "--all",
            "--date=iso-strict",
            "--pretty=format:%H%x1f%ad%x1f%an%x1f%s",
            "--max-count=500",
        ],
        repo,
    )
    commits: list[RepoCommit] = []
    for line in log.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 4:
            continue
        commit_hash, timestamp, author, subject = parts
        commits.append(
            RepoCommit(
                repo=cfg["name"],
                repo_key=cfg["key"],
                hash=commit_hash,
                time=timestamp,
                author=author,
                subject=subject,
                files=changed_files(repo, commit_hash),
            )
        )
    head = run(["git", "rev-parse", "HEAD"], repo).strip()
    branch = run(["git", "branch", "--show-current"], repo).strip()
    remotes = run(["git", "remote", "-v"], repo).strip().splitlines()
    return commits, {
        "key": cfg["key"],
        "name": cfg["name"],
        "path": str(repo),
        "branch": branch,
        "head": head,
        "status": repo_status(repo),
        "remote": cfg["remote"],
        "github": cfg["github"],
        "remotes": remotes,
    }


def merge_commits(commits: list[RepoCommit]) -> list[dict[str, Any]]:
    by_hash: dict[str, list[RepoCommit]] = defaultdict(list)
    for commit in commits:
        by_hash[commit.hash].append(commit)

    merged: list[dict[str, Any]] = []
    for commit_hash, group in by_hash.items():
        primary = sorted(group, key=lambda item: item.repo_key)[0]
        files_by_repo = {
            item.repo: item.files
            for item in sorted(group, key=lambda item: item.repo_key)
        }
        all_files = [file for item in group for file in item.files]
        kind, label, scope = parse_type(primary.subject)
        merged.append(
            {
                "hash": commit_hash,
                "short_hash": commit_hash[:7],
                "time": primary.time,
                "author": primary.author,
                "subject": primary.subject,
                "type": kind,
                "type_label": label,
                "scope": scope,
                "repos": sorted({item.repo for item in group}),
                "modules": infer_modules(primary.repo_key, all_files, primary.subject),
                "files_by_repo": files_by_repo,
                "file_count": len(all_files),
            }
        )
    merged.sort(key=lambda item: item["time"], reverse=True)
    return merged


def load_server_snapshot(path: Path | None) -> dict[str, Any]:
    if not path:
        return {
            "ok": False,
            "source": "not-collected",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": "No server snapshot file was provided.",
        }
    return json.loads(path.read_text(encoding="utf-8"))


def load_manual_records(root: Path) -> list[dict[str, Any]]:
    records_by_id: dict[str, dict[str, Any]] = {}
    for path in [
        root / "development_records.json",
        root / "XJie_IOS" / "development_records.json",
        root / "XJie_And" / "development_records.json",
    ]:
        if not path.exists():
            continue
        items = json.loads(path.read_text(encoding="utf-8"))
        for item in items:
            record_id = item.get("id") or f"{item.get('time')}:{item.get('feature')}"
            files_by_repo = item.get("files_by_repo") or {}
            file_count = sum(len(files) for files in files_by_repo.values())
            records_by_id[record_id] = {
                "hash": record_id,
                "short_hash": "record",
                "time": item.get("time", ""),
                "author": item.get("author", "Codex"),
                "subject": item.get("feature", ""),
                "description": item.get("description", ""),
                "type": item.get("type", "record"),
                "type_label": item.get("type_label", item.get("type", "记录")),
                "scope": item.get("scope", ""),
                "repos": item.get("repos", []),
                "modules": item.get("modules", []),
                "files_by_repo": files_by_repo,
                "file_count": file_count,
                "verification": item.get("verification", []),
                "source": "manual-record",
            }
    return sorted(records_by_id.values(), key=lambda item: item["time"], reverse=True)


def build_project_overview(commits: list[dict[str, Any]], repos: list[dict[str, Any]], server: dict[str, Any]) -> dict[str, Any]:
    latest_by_repo: dict[str, dict[str, Any]] = {}
    for repo in ["iOS", "Android"]:
        latest_by_repo[repo] = next((item for item in commits if repo in item["repos"]), {})
    earliest = commits[-1]["time"] if commits else ""
    latest = commits[0]["time"] if commits else ""
    db_counts = server.get("database", {}).get("counts", {}) if server.get("ok") else {}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": "/Users/linlin/Desktop/X",
        "repos": repos,
        "commit_count": len(commits),
        "latest_commit_time": latest,
        "earliest_commit_time": earliest,
        "latest_by_repo": latest_by_repo,
        "db_counts": db_counts,
        "server_status": {
            "ok": server.get("ok", False),
            "host": server.get("host", {}).get("hostname", ""),
            "uptime": server.get("host", {}).get("uptime", ""),
            "unhealthy_containers": server.get("health", {}).get("unhealthy_containers", []),
        },
    }


def json_script(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def render_html(data: dict[str, Any]) -> str:
    title = "Xjie 双端开发历史与运维 Dashboard"
    payload = json_script(data)
    generated = html.escape(data["overview"]["generated_at"])
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      --bg: #f6f8f7;
      --surface: #ffffff;
      --surface-2: #eef4f1;
      --text: #1b2328;
      --muted: #5d6b66;
      --line: #d8e1dc;
      --green: #1f7a63;
      --blue: #2f5f9f;
      --amber: #a45f14;
      --red: #a93932;
      --shadow: 0 10px 24px rgba(25, 42, 38, 0.08);
      color-scheme: light;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
      line-height: 1.45;
    }}
    button, input, select {{
      font: inherit;
    }}
    .app {{
      min-height: 100vh;
    }}
    header {{
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(246, 248, 247, 0.94);
      backdrop-filter: blur(14px);
      border-bottom: 1px solid var(--line);
    }}
    .topbar {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 18px 24px 14px;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 16px;
      align-items: center;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(22px, 3vw, 34px);
      letter-spacing: 0;
      line-height: 1.1;
    }}
    .subtitle {{
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 14px;
    }}
    .actions {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .btn {{
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      border-radius: 6px;
      padding: 9px 12px;
      cursor: pointer;
      min-height: 38px;
    }}
    .btn.primary {{
      background: var(--green);
      border-color: var(--green);
      color: white;
    }}
    .btn:focus, input:focus, select:focus {{
      outline: 2px solid rgba(31, 122, 99, 0.24);
      outline-offset: 2px;
    }}
    nav {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 0 24px 12px;
      display: flex;
      gap: 8px;
      overflow-x: auto;
    }}
    .tab {{
      border: 1px solid var(--line);
      background: transparent;
      border-radius: 6px;
      padding: 8px 12px;
      color: var(--muted);
      cursor: pointer;
      white-space: nowrap;
    }}
    .tab.active {{
      color: var(--green);
      border-color: rgba(31, 122, 99, 0.35);
      background: #e7f2ee;
    }}
    main {{
      max-width: 1320px;
      margin: 0 auto;
      padding: 22px 24px 54px;
    }}
    .view {{ display: none; }}
    .view.active {{ display: block; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(12, 1fr);
      gap: 14px;
    }}
    .panel {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      padding: 18px;
    }}
    .span-3 {{ grid-column: span 3; }}
    .span-4 {{ grid-column: span 4; }}
    .span-5 {{ grid-column: span 5; }}
    .span-6 {{ grid-column: span 6; }}
    .span-7 {{ grid-column: span 7; }}
    .span-8 {{ grid-column: span 8; }}
    .span-12 {{ grid-column: span 12; }}
    .metric-label {{
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 7px;
    }}
    .metric-value {{
      font-size: 28px;
      font-weight: 700;
      line-height: 1.1;
      word-break: break-word;
    }}
    .metric-note {{
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .section-title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
    }}
    h2 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: 0;
    }}
    .filters {{
      display: grid;
      grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(140px, 190px));
      gap: 10px;
      margin-bottom: 14px;
    }}
    input, select {{
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      padding: 10px 11px;
      color: var(--text);
      min-height: 40px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    th, td {{
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 11px 10px;
      vertical-align: top;
    }}
    th {{
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      text-transform: uppercase;
    }}
    .badge-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      padding: 3px 7px;
      border-radius: 999px;
      background: var(--surface-2);
      color: var(--muted);
      font-size: 12px;
      white-space: nowrap;
    }}
    .badge.green {{ background: #e2f1ea; color: var(--green); }}
    .badge.blue {{ background: #e5edf8; color: var(--blue); }}
    .badge.amber {{ background: #f6eadb; color: var(--amber); }}
    .badge.red {{ background: #f8e3e1; color: var(--red); }}
    details {{
      margin-top: 8px;
    }}
    summary {{
      cursor: pointer;
      color: var(--green);
    }}
    .file-list {{
      margin: 8px 0 0;
      padding-left: 16px;
      color: var(--muted);
      font-size: 12px;
      max-height: 220px;
      overflow: auto;
    }}
    code, pre {{
      font-family: "SF Mono", Menlo, Consolas, monospace;
      font-size: 12px;
    }}
    pre {{
      margin: 0;
      white-space: pre-wrap;
      word-break: break-word;
      background: #111816;
      color: #dfe9e4;
      padding: 14px;
      border-radius: 8px;
      overflow: auto;
    }}
    .timeline {{
      display: grid;
      gap: 10px;
    }}
    .timeline-item {{
      display: grid;
      grid-template-columns: 170px 1fr;
      gap: 16px;
      border-left: 3px solid var(--line);
      padding: 10px 0 10px 14px;
    }}
    .muted {{ color: var(--muted); }}
    .small {{ font-size: 13px; }}
    .status-line {{
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 13px;
    }}
    .dot {{
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: var(--green);
      display: inline-block;
      flex: 0 0 auto;
    }}
    .dot.warn {{ background: var(--amber); }}
    .dot.bad {{ background: var(--red); }}
    .server-grid {{
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }}
    .container-row {{
      display: grid;
      grid-template-columns: minmax(130px, 1.2fr) minmax(130px, 1fr) 110px 110px 1fr;
      gap: 10px;
      padding: 10px 0;
      border-bottom: 1px solid var(--line);
      align-items: start;
      font-size: 13px;
    }}
    .container-row.header {{
      color: var(--muted);
      font-weight: 650;
      font-size: 12px;
    }}
    .table-counts {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
    }}
    .count-item {{
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px;
      background: #fbfcfb;
      min-width: 0;
    }}
    .count-item strong {{
      display: block;
      font-size: 18px;
      margin-top: 3px;
    }}
    @media (max-width: 980px) {{
      .topbar {{ grid-template-columns: 1fr; }}
      .actions {{ justify-content: flex-start; }}
      .span-3, .span-4, .span-5, .span-6, .span-7, .span-8 {{ grid-column: span 12; }}
      .filters {{ grid-template-columns: 1fr; }}
      .server-grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
      .container-row {{ grid-template-columns: 1fr; }}
      table, thead, tbody, tr, th, td {{ display: block; }}
      thead {{ display: none; }}
      td {{ padding: 8px 0; }}
      tr {{ border-bottom: 1px solid var(--line); padding: 10px 0; }}
    }}
    @media (max-width: 640px) {{
      main, .topbar, nav {{ padding-left: 14px; padding-right: 14px; }}
      .server-grid, .table-counts {{ grid-template-columns: 1fr; }}
      .timeline-item {{ grid-template-columns: 1fr; gap: 4px; }}
    }}
  </style>
</head>
<body>
<div class="app">
  <header>
    <div class="topbar">
      <div>
        <h1>{html.escape(title)}</h1>
        <p class="subtitle">生成时间：{generated}。页面包含离线历史快照；服务器数据可通过受保护的运维 API 实时刷新。</p>
      </div>
      <div class="actions">
        <button class="btn" id="exportJsonBtn">导出 JSON</button>
        <button class="btn primary" id="refreshServerBtn">刷新服务器</button>
      </div>
    </div>
    <nav aria-label="Dashboard tabs">
      <button class="tab active" data-tab="overview">总览</button>
      <button class="tab" data-tab="history">开发历史</button>
      <button class="tab" data-tab="server">服务器</button>
      <button class="tab" data-tab="features">功能库</button>
      <button class="tab" data-tab="map">项目地图</button>
      <button class="tab" data-tab="runbook">运行指引</button>
    </nav>
  </header>
  <main>
    <section class="view active" id="view-overview"></section>
    <section class="view" id="view-history"></section>
    <section class="view" id="view-server"></section>
    <section class="view" id="view-features"></section>
    <section class="view" id="view-map"></section>
    <section class="view" id="view-runbook"></section>
  </main>
</div>
<script>
window.XJIE_DASHBOARD_DATA = {payload};
</script>
<script>
(function () {{
  const DATA = window.XJIE_DASHBOARD_DATA;
  const API_ORIGIN = location.protocol === "file:" ? "http://127.0.0.1:8791" : location.origin;
  const SNAPSHOT_API = `${{API_ORIGIN}}/api/server/snapshot`;
  let serverSnapshot = DATA.server;
  let opsToken = localStorage.getItem("xjie_ops_admin_token") || "";

  const $ = (selector) => document.querySelector(selector);
  const esc = (value) => String(value ?? "").replace(/[&<>"']/g, (ch) => ({{
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }}[ch]));
  const fmtTime = (value) => {{
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("zh-CN", {{ hour12: false }});
  }};
  const typeBadgeClass = (label) => {{
    if (label === "功能") return "green";
    if (label === "修复") return "amber";
    if (label === "文档") return "blue";
    if (label === "重构") return "blue";
    return "";
  }};
  const unique = (items) => Array.from(new Set(items.filter(Boolean)));

  function setTab(name) {{
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    document.querySelectorAll(".view").forEach((view) => view.classList.toggle("active", view.id === "view-" + name));
  }}

  function badge(text, cls = "") {{
    return `<span class="badge ${{cls}}">${{esc(text)}}</span>`;
  }}

  function renderOverview() {{
    const o = DATA.overview;
    const db = o.db_counts || {{}};
    const unhealthy = o.server_status.unhealthy_containers || [];
    $("#view-overview").innerHTML = `
      <div class="grid">
        <div class="panel span-3"><div class="metric-label">Git 提交</div><div class="metric-value">${{o.commit_count}}</div><div class="metric-note">${{fmtTime(o.earliest_commit_time)}} 至 ${{fmtTime(o.latest_commit_time)}}</div></div>
        <div class="panel span-3"><div class="metric-label">用户数</div><div class="metric-value">${{db.user_account ?? "-"}}</div><div class="metric-note">来自服务器快照 user_account</div></div>
        <div class="panel span-3"><div class="metric-label">血糖读数</div><div class="metric-value">${{db.glucose_readings ?? "-"}}</div><div class="metric-note">glucose_readings</div></div>
        <div class="panel span-3"><div class="metric-label">服务器状态</div><div class="metric-value">${{unhealthy.length ? "需检查" : (o.server_status.ok ? "正常" : "离线")}}</div><div class="metric-note">${{unhealthy.length ? "异常容器：" + unhealthy.join(", ") : (o.server_status.uptime || "等待实时刷新")}}</div></div>
        <div class="panel span-6">
          <div class="section-title"><h2>最新 iOS 提交</h2>${{badge("iOS", "blue")}}</div>
          ${{commitSummary(o.latest_by_repo.iOS)}}
        </div>
        <div class="panel span-6">
          <div class="section-title"><h2>最新 Android 提交</h2>${{badge("Android", "green")}}</div>
          ${{commitSummary(o.latest_by_repo.Android)}}
        </div>
        <div class="panel span-12">
          <div class="section-title"><h2>近期开发时间线</h2><button class="btn" data-jump-history>查看全部</button></div>
          <div class="timeline">${{DATA.history.slice(0, 10).map(timelineItem).join("")}}</div>
        </div>
      </div>
    `;
    $("[data-jump-history]")?.addEventListener("click", () => setTab("history"));
  }}

  function commitSummary(commit) {{
    if (!commit || !commit.hash) return `<p class="muted">暂无记录</p>`;
    return `
      <div class="badge-row">${{commit.repos.map((repo) => badge(repo, repo === "Android" ? "green" : "blue")).join("")}}${{badge(commit.type_label, typeBadgeClass(commit.type_label))}}</div>
      <p><strong>${{esc(commit.subject)}}</strong></p>
      <p class="muted small">${{fmtTime(commit.time)}} · ${{esc(commit.short_hash)}} · 文件变更 ${{commit.file_count}} 个</p>
    `;
  }}

  function timelineItem(commit) {{
    return `
      <div class="timeline-item">
        <div class="muted small">${{fmtTime(commit.time)}}<br><code>${{esc(commit.short_hash)}}</code></div>
        <div>
          <div class="badge-row">${{commit.repos.map((repo) => badge(repo, repo === "Android" ? "green" : "blue")).join("")}}${{commit.source === "manual-record" ? badge("记录", "amber") : ""}}${{badge(commit.type_label, typeBadgeClass(commit.type_label))}}${{commit.modules.map((m) => badge(m)).join("")}}</div>
          <div style="margin-top:6px"><strong>${{esc(commit.subject)}}</strong></div>
          ${{commit.description ? `<div class="muted small">${{esc(commit.description)}}</div>` : ""}}
        </div>
      </div>
    `;
  }}

  function renderHistory() {{
    const types = unique(DATA.history.map((c) => c.type_label)).sort();
    const modules = unique(DATA.history.flatMap((c) => c.modules)).sort();
    $("#view-history").innerHTML = `
      <div class="panel">
        <div class="section-title"><h2>开发历史</h2><span class="muted small">包含双仓库 Git 历史与人工发布记录，重复 hash 已合并</span></div>
        <div class="filters">
          <input id="historySearch" placeholder="搜索功能、提交、文件路径">
          <select id="historyRepo"><option value="">全部仓库</option><option>iOS</option><option>Android</option></select>
          <select id="historyType"><option value="">全部类型</option>${{types.map((t) => `<option>${{esc(t)}}</option>`).join("")}}</select>
          <select id="historyModule"><option value="">全部模块</option>${{modules.map((m) => `<option>${{esc(m)}}</option>`).join("")}}</select>
        </div>
        <div id="historyTable"></div>
      </div>
    `;
    ["historySearch", "historyRepo", "historyType", "historyModule"].forEach((id) => $("#" + id).addEventListener("input", updateHistory));
    updateHistory();
  }}

  function commitMatches(commit, q, repo, type, module) {{
    const text = [
      commit.subject,
      commit.short_hash,
      commit.author,
      commit.repos.join(" "),
      commit.modules.join(" "),
      Object.values(commit.files_by_repo || {{}}).flat().map((f) => f.path).join(" ")
    ].join(" ").toLowerCase();
    return (!q || text.includes(q)) &&
      (!repo || commit.repos.includes(repo)) &&
      (!type || commit.type_label === type) &&
      (!module || commit.modules.includes(module));
  }}

  function updateHistory() {{
    const q = $("#historySearch").value.trim().toLowerCase();
    const repo = $("#historyRepo").value;
    const type = $("#historyType").value;
    const module = $("#historyModule").value;
    const rows = DATA.history.filter((commit) => commitMatches(commit, q, repo, type, module));
    $("#historyTable").innerHTML = `
      <p class="muted small">当前筛选 ${{rows.length}} 条。</p>
      <table>
        <thead><tr><th>时间</th><th>类型</th><th>仓库/模块</th><th>描述</th><th>文件变化</th></tr></thead>
        <tbody>${{rows.map(historyRow).join("")}}</tbody>
      </table>
    `;
  }}

  function historyRow(commit) {{
    const filesHtml = Object.entries(commit.files_by_repo || {{}}).map(([repo, files]) => `
      <strong>${{esc(repo)}}</strong>
      <ul class="file-list">${{files.map((f) => `<li><code>${{esc(f.status)}} ${{esc(f.path)}}</code></li>`).join("")}}</ul>
    `).join("");
    return `
      <tr>
        <td>${{fmtTime(commit.time)}}<br><code>${{esc(commit.short_hash)}}</code></td>
        <td>${{badge(commit.type_label, typeBadgeClass(commit.type_label))}}${{commit.scope ? `<div class="muted small">${{esc(commit.scope)}}</div>` : ""}}</td>
        <td><div class="badge-row">${{commit.repos.map((repo) => badge(repo, repo === "Android" ? "green" : "blue")).join("")}}${{commit.source === "manual-record" ? badge("记录", "amber") : ""}}${{commit.modules.map((m) => badge(m)).join("")}}</div></td>
        <td><strong>${{esc(commit.subject)}}</strong><div class="muted small">${{esc(commit.author)}}${{commit.description ? " · " + esc(commit.description) : ""}}</div>${{Array.isArray(commit.verification) && commit.verification.length ? `<div class="muted small">验证：${{commit.verification.map(esc).join("；")}}</div>` : ""}}</td>
        <td><details><summary>${{commit.file_count}} 个文件</summary>${{filesHtml}}</details></td>
      </tr>
    `;
  }}

  function renderServer() {{
    const snapshot = serverSnapshot || {{}};
    const ok = Boolean(snapshot.ok);
    const unhealthy = snapshot.health?.unhealthy_containers || [];
    const containers = snapshot.containers || [];
    const counts = snapshot.database?.counts || {{}};
    const memory = snapshot.resources?.memory_mb || {{}};
    const disk = snapshot.resources?.disk || {{}};
    $("#view-server").innerHTML = `
      <div class="grid">
        <div class="panel span-12">
          <div class="section-title">
            <h2>服务器实时 Dashboard</h2>
            <div class="status-line"><span class="dot ${{ok ? (unhealthy.length ? "warn" : "") : "bad"}}"></span>${{ok ? "已加载服务器快照" : "使用离线快照或等待本机 API"}}</div>
          </div>
          <p class="muted small">浏览器不会保存 SSH/数据库密码。服务器部署时使用小捷管理员账号登录后刷新；本机打开文件时仍可使用 <code>127.0.0.1:8791</code> 开发代理。</p>
          <div id="opsLoginBox" style="margin-top:14px;display:${{opsToken ? "none" : "grid"}};grid-template-columns:minmax(160px,220px) minmax(160px,220px) auto;gap:8px;align-items:center">
            <input id="opsPhone" placeholder="管理员手机号" autocomplete="username">
            <input id="opsPassword" type="password" placeholder="密码" autocomplete="current-password">
            <button class="btn primary" id="opsLoginBtn">登录运维 API</button>
          </div>
          <div class="status-line" style="margin-top:10px">
            <span class="dot ${{opsToken ? "" : "warn"}}"></span>
            <span id="opsAuthState">${{opsToken ? "已保存管理员 token，可刷新实时数据" : "未登录时只能查看离线快照"}}</span>
            ${{opsToken ? '<button class="btn" id="opsLogoutBtn" style="padding:5px 9px;min-height:30px">退出运维登录</button>' : ""}}
          </div>
        </div>
        <div class="panel span-12">
          <div class="server-grid">
            <div><div class="metric-label">Host</div><div class="metric-value">${{esc(snapshot.host?.hostname || "-")}}</div><div class="metric-note">${{esc(snapshot.ssh_host || "")}}</div></div>
            <div><div class="metric-label">Uptime</div><div class="metric-value" style="font-size:22px">${{esc(snapshot.host?.uptime || "-")}}</div><div class="metric-note">${{esc(snapshot.host?.server_time || "")}}</div></div>
            <div><div class="metric-label">Disk</div><div class="metric-value">${{esc(disk.used_percent || "-")}}</div><div class="metric-note">${{esc(disk.used || "-")}} / ${{esc(disk.size || "-")}}</div></div>
            <div><div class="metric-label">Memory</div><div class="metric-value">${{memory.used != null ? memory.used + " MB" : "-"}}</div><div class="metric-note">available ${{memory.available != null ? memory.available + " MB" : "-"}}</div></div>
          </div>
        </div>
        <div class="panel span-7">
          <div class="section-title"><h2>Docker 容器</h2>${{unhealthy.length ? badge("需检查: " + unhealthy.join(", "), "amber") : badge("healthy / none", "green")}}</div>
          <div class="container-row header"><div>名称</div><div>镜像</div><div>CPU</div><div>内存</div><div>状态</div></div>
          ${{containers.map(containerRow).join("") || '<p class="muted">无容器数据</p>'}}
        </div>
        <div class="panel span-5">
          <div class="section-title"><h2>数据库</h2>${{badge("migration " + (snapshot.database?.migration || "-"), "blue")}}</div>
          <div class="table-counts">${{Object.entries(counts).map(([name, count]) => `<div class="count-item"><span class="muted small">${{esc(name)}}</span><strong>${{count ?? "-"}}</strong></div>`).join("")}}</div>
        </div>
        <div class="panel span-12">
          <div class="section-title"><h2>启动本机 API</h2><button class="btn" id="copyRunCommand">复制命令</button></div>
          <pre id="runCommand">cd /Users/linlin/Desktop/X
python3 XJie_IOS/tools/xjie_dashboard_api.py --root /Users/linlin/Desktop/X --port 8791</pre>
          <p class="muted small">服务器部署命令：<code>python3 tools/xjie_dashboard_api.py --server-mode --require-auth --host 0.0.0.0 --port 8791 --api-base http://127.0.0.1:8000 --html development_history.html</code></p>
          <p class="muted small" id="serverMessage">${{esc(snapshot.error || "")}}</p>
        </div>
      </div>
    `;
    $("#copyRunCommand")?.addEventListener("click", () => navigator.clipboard?.writeText($("#runCommand").textContent.trim()));
    $("#opsLoginBtn")?.addEventListener("click", loginOps);
    $("#opsLogoutBtn")?.addEventListener("click", logoutOps);
  }}

  function containerRow(item) {{
    const healthClass = item.health && !["none", "healthy", "unknown"].includes(item.health) ? "amber" : "green";
    return `
      <div class="container-row">
        <div><strong>${{esc(item.name)}}</strong><div class="muted small">${{esc(item.ports)}}</div></div>
        <div class="small">${{esc(item.image)}}</div>
        <div>${{esc(item.cpu || "-")}}</div>
        <div>${{esc(item.memory || "-")}}</div>
        <div>${{badge(item.health || "unknown", healthClass)}}<div class="muted small">${{esc(item.status || "")}}</div></div>
      </div>
    `;
  }}

  async function loginOps() {{
    const phone = $("#opsPhone")?.value.trim();
    const password = $("#opsPassword")?.value || "";
    if (!phone || !password) {{
      $("#serverMessage").textContent = "请输入管理员手机号和密码";
      return;
    }}
    const response = await fetch(`${{API_ORIGIN}}/api/auth/login`, {{
      method: "POST",
      headers: {{ "Content-Type": "application/json" }},
      body: JSON.stringify({{ phone, password }})
    }});
    const payload = await response.json().catch(() => ({{}}));
    if (!response.ok || !payload.access_token) {{
      $("#serverMessage").textContent = payload.detail || "登录失败";
      return;
    }}
    opsToken = payload.access_token;
    localStorage.setItem("xjie_ops_admin_token", opsToken);
    await refreshServer();
  }}

  function logoutOps() {{
    opsToken = "";
    localStorage.removeItem("xjie_ops_admin_token");
    renderServer();
  }}

  async function refreshServer() {{
    const btn = $("#refreshServerBtn");
    btn.disabled = true;
    btn.textContent = "刷新中";
    try {{
      const headers = opsToken ? {{ Authorization: `Bearer ${{opsToken}}` }} : {{}};
      const response = await fetch(SNAPSHOT_API, {{ cache: "no-store", headers }});
      const payload = await response.json();
      if (response.status === 401 || response.status === 403) {{
        throw new Error("需要管理员登录后刷新服务器实时数据");
      }}
      if (!response.ok || !payload.ok) throw new Error(payload.error || "Dashboard API returned an error");
      serverSnapshot = payload;
      DATA.server = payload;
      DATA.overview.server_status = {{
        ok: true,
        host: payload.host?.hostname || "",
        uptime: payload.host?.uptime || "",
        unhealthy_containers: payload.health?.unhealthy_containers || []
      }};
      DATA.overview.db_counts = payload.database?.counts || {{}};
      renderOverview();
      renderServer();
      renderFeatures();
      setTab("server");
    }} catch (error) {{
      serverSnapshot = {{ ok: false, error: error.message, generated_at: new Date().toISOString() }};
      renderServer();
      setTab("server");
    }} finally {{
      btn.disabled = false;
      btn.textContent = "刷新服务器";
    }}
  }}

  function renderFeatures() {{
    const snapshot = serverSnapshot || {{}};
    const features = snapshot.features || {{}};
    const flags = features.feature_flags || [];
    const skills = features.skills || [];
    const parity = features.feature_parity || [];
    const columns = snapshot.database?.columns || [];
    const repos = snapshot.repos || [];
    $("#view-features").innerHTML = `
      <div class="grid">
        <div class="panel span-12">
          <div class="section-title">
            <h2>双端功能库</h2>
            <button class="btn primary" data-refresh-features>刷新实时功能库</button>
          </div>
          <p class="muted small">来自生产数据库 <code>feature_parity</code>、<code>feature_flags</code>、<code>skills</code> 与服务器 Git 状态。需要先在“服务器”页登录管理员账号。</p>
        </div>
        <div class="panel span-4"><div class="metric-label">端对齐功能</div><div class="metric-value">${{parity.length}}</div><div class="metric-note">feature_parity</div></div>
        <div class="panel span-4"><div class="metric-label">功能开关</div><div class="metric-value">${{flags.length}}</div><div class="metric-note">feature_flags</div></div>
        <div class="panel span-4"><div class="metric-label">AI 技能</div><div class="metric-value">${{skills.length}}</div><div class="metric-note">skills</div></div>
        <div class="panel span-12">
          <div class="section-title"><h2>双端对齐</h2>${{badge(parity.length ? "实时" : "暂无数据", parity.length ? "green" : "amber")}}</div>
          <div style="overflow-x:auto"><table>
            <thead><tr><th>模块</th><th>功能</th><th>优先级</th><th>iOS</th><th>Android</th><th>后端 API</th><th>更新时间</th></tr></thead>
            <tbody>${{parity.map((item) => `<tr><td>${{esc(item.module)}}</td><td><strong>${{esc(item.name)}}</strong><div class="muted small">${{esc(item.notes || "")}}</div></td><td>${{esc(item.priority)}}</td><td>${{badge(item.ios_status || "-", item.ios_status === "shipped" ? "green" : "amber")}}</td><td>${{badge(item.android_status || "-", item.android_status === "shipped" ? "green" : "amber")}}</td><td><code>${{esc(item.backend_apis || "")}}</code></td><td>${{fmtTime(item.updated_at)}}</td></tr>`).join("") || '<tr><td colspan="7" class="empty">暂无端对齐数据，可在现有管理后台“端对齐”页导入预设。</td></tr>'}}</tbody>
          </table></div>
        </div>
        <div class="panel span-6">
          <div class="section-title"><h2>功能开关</h2></div>
          <div style="overflow-x:auto"><table>
            <thead><tr><th>Key</th><th>状态</th><th>灰度</th><th>描述</th></tr></thead>
            <tbody>${{flags.map((item) => `<tr><td><code>${{esc(item.key)}}</code></td><td>${{badge(item.enabled ? "启用" : "停用", item.enabled ? "green" : "amber")}}</td><td>${{item.rollout_pct ?? "-"}}%</td><td>${{esc(item.description || "")}}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">暂无功能开关</td></tr>'}}</tbody>
          </table></div>
        </div>
        <div class="panel span-6">
          <div class="section-title"><h2>AI 技能</h2></div>
          <div style="overflow-x:auto"><table>
            <thead><tr><th>优先级</th><th>Key</th><th>名称</th><th>触发</th></tr></thead>
            <tbody>${{skills.map((item) => `<tr><td>${{item.priority}}</td><td><code>${{esc(item.key)}}</code></td><td>${{esc(item.name)}} ${{badge(item.enabled ? "启用" : "停用", item.enabled ? "green" : "amber")}}</td><td>${{esc(item.trigger_hint || "始终")}}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">暂无技能</td></tr>'}}</tbody>
          </table></div>
        </div>
        <div class="panel span-7">
          <div class="section-title"><h2>数据库结构</h2>${{badge(`${{snapshot.database?.table_count || 0}} tables`, "blue")}}</div>
          <div style="max-height:420px;overflow:auto"><table>
            <thead><tr><th>表</th><th>字段</th><th>类型</th><th>可空</th></tr></thead>
            <tbody>${{columns.slice(0, 260).map((c) => `<tr><td><code>${{esc(c.table_name)}}</code></td><td>${{esc(c.column_name)}}</td><td>${{esc(c.data_type)}}</td><td>${{esc(c.is_nullable)}}</td></tr>`).join("") || '<tr><td colspan="4" class="empty">暂无结构数据</td></tr>'}}</tbody>
          </table></div>
        </div>
        <div class="panel span-5">
          <div class="section-title"><h2>服务器仓库</h2></div>
          <div class="timeline">${{repos.map((repo) => `<div class="timeline-item" style="grid-template-columns:1fr"><div><strong>${{esc(repo.path)}}</strong><div class="muted small">${{repo.is_git ? esc(repo.latest || repo.head || "") : "not a git repo"}}</div><div class="badge-row">${{repo.branch ? badge(repo.branch, "blue") : ""}}${{repo.status ? badge("dirty", "amber") : badge("clean", "green")}}</div></div></div>`).join("") || '<p class="muted">暂无仓库数据</p>'}}</div>
        </div>
      </div>
    `;
    $("[data-refresh-features]")?.addEventListener("click", refreshServer);
  }}

  function renderMap() {{
    $("#view-map").innerHTML = `
      <div class="grid">
        <div class="panel span-6"><h2>iOS 仓库</h2><p>SwiftUI + Combine，App 代码位于 <code>XJie_IOS/Xjie/Xjie</code>，后端副本位于 <code>XJie_IOS/backend</code>。</p><p class="muted small">核心模块：Home、Glucose、Meals、Chat、HealthData、Omics、Settings、Medications、Elderly。</p></div>
        <div class="panel span-6"><h2>Android 仓库</h2><p>Kotlin + Jetpack Compose + Hilt，App 代码位于 <code>XJie_And/Android/app/src/main/java/com/xjie/app</code>。</p><p class="muted small">核心模块：feature/*、core/network、core/model、navigation、ui components。</p></div>
        <div class="panel span-6"><h2>共享后端</h2><p>FastAPI + SQLAlchemy + PostgreSQL/TimescaleDB + Redis。主要目录：<code>backend/app/routers</code>、<code>models</code>、<code>services</code>、<code>providers</code>。</p></div>
        <div class="panel span-6"><h2>已知运维点</h2><p>生产 ECS 通过 Docker 运行 <code>xjie-api</code>、<code>xjie-cgm</code>、<code>timescaledb</code>、Redis。当前快照显示 <code>xjie-cgm</code> 为 unhealthy，需要后续排查。</p></div>
      </div>
    `;
  }}

  function renderRunbook() {{
    $("#view-runbook").innerHTML = `
      <div class="grid">
        <div class="panel span-6">
          <h2>后续开发默认流程</h2>
          <ol>
            <li>先判断变更是否影响后端契约；影响时同步 iOS/Android models、repositories/API、UI 状态。</li>
            <li>双端分别运行可用的单元测试或构建检查；没有设备时至少跑编译/静态校验。</li>
            <li>更新本 HTML：记录功能、类型、文件变化和时间戳。</li>
            <li>分别提交并推送 <code>XJie_IOS</code> 和 <code>Xjie_andro</code> 对应远端。</li>
          </ol>
        </div>
        <div class="panel span-6">
          <h2>常用命令</h2>
          <pre>cd /Users/linlin/Desktop/X/XJie_IOS
python3 -m pytest backend/tests -q

cd /Users/linlin/Desktop/X/XJie_And/Android
JAVA_HOME=/Applications/Android\\ Studio.app/Contents/jbr/Contents/Home ./gradlew :app:assembleDebug

cd /Users/linlin/Desktop/X
python3 XJie_IOS/tools/xjie_dashboard_api.py --once --root /Users/linlin/Desktop/X</pre>
        </div>
        <div class="panel span-12">
          <h2>重新生成 HTML</h2>
          <pre>cd /Users/linlin/Desktop/X
python3 XJie_IOS/tools/xjie_dashboard_api.py --once --root /Users/linlin/Desktop/X > /tmp/xjie_server_snapshot.json
python3 XJie_IOS/tools/generate_development_history.py --workspace /Users/linlin/Desktop/X --server-snapshot /tmp/xjie_server_snapshot.json</pre>
        </div>
      </div>
    `;
  }}

  function exportJson() {{
    const blob = new Blob([JSON.stringify(DATA, null, 2)], {{ type: "application/json" }});
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "xjie-development-history.json";
    link.click();
    URL.revokeObjectURL(url);
  }}

  document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => setTab(tab.dataset.tab)));
  $("#refreshServerBtn").addEventListener("click", refreshServer);
  $("#exportJsonBtn").addEventListener("click", exportJson);
  renderOverview();
  renderHistory();
  renderServer();
  renderFeatures();
  renderMap();
  renderRunbook();
}}());
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate development_history.html for Xjie.")
    parser.add_argument("--workspace", type=Path, default=Path.cwd(), help="Workspace root containing XJie_IOS and XJie_And")
    parser.add_argument("--server-snapshot", type=Path, default=None, help="JSON snapshot from xjie_dashboard_api.py --once")
    parser.add_argument("--output", type=Path, action="append", default=[], help="Extra output path")
    args = parser.parse_args()

    root = args.workspace.resolve()
    all_commits: list[RepoCommit] = []
    repo_meta: list[dict[str, Any]] = []
    for cfg in REPO_CONFIG:
        commits, meta = collect_repo(root, cfg)
        all_commits.extend(commits)
        repo_meta.append(meta)

    commits = merge_commits(all_commits)
    manual_records = load_manual_records(root)
    history = sorted([*manual_records, *commits], key=lambda item: item["time"], reverse=True)
    server = load_server_snapshot(args.server_snapshot)
    data = {
        "overview": build_project_overview(commits, repo_meta, server),
        "history": history,
        "commits": commits,
        "server": server,
    }
    content = render_html(data)

    outputs = [
        root / "development_history.html",
        root / "XJie_IOS" / "development_history.html",
        root / "XJie_And" / "development_history.html",
        *[path.resolve() for path in args.output],
    ]
    for path in outputs:
        path.write_text(content, encoding="utf-8")
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
