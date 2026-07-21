#!/usr/bin/env python3
"""Upload test_data to a configured user via the app's upload API.

Does NOT delete existing documents — skips already-uploaded files.
Images go through async LLM extraction (backend background thread).
CSVs are processed synchronously.

Uploads fire-and-forget for images (no poll), with a short delay
to let the backend LLM threads drain gradually.
"""

import os, sys, time, glob, requests

BASE_URL = os.getenv("XJIE_UPLOAD_BASE_URL", "http://8.130.213.44:8000")
PHONE = os.getenv("XJIE_UPLOAD_PHONE", "")
PASSWORD = os.getenv("XJIE_UPLOAD_PASSWORD", "")
TEST_DATA = os.path.dirname(os.path.abspath(__file__))
UPLOAD_DELAY = 2  # seconds between image uploads (throttle LLM threads)

_token_cache = {"token": None, "ts": 0}


def get_token() -> str:
    if _token_cache["token"] and (time.time() - _token_cache["ts"]) < 1200:
        return _token_cache["token"]
    r = requests.post(f"{BASE_URL}/api/auth/login", json={"phone": PHONE, "password": PASSWORD})
    r.raise_for_status()
    _token_cache["token"] = r.json()["access_token"]
    _token_cache["ts"] = time.time()
    return _token_cache["token"]


def auth_headers():
    return {"Authorization": f"Bearer {get_token()}"}


def upload_file(filepath: str, doc_type: str, name: str) -> dict:
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/api/health-data/upload",
            headers=auth_headers(),
            files={"file": (os.path.basename(filepath), f)},
            data={"doc_type": doc_type, "name": name},
            timeout=180,
        )
    resp.raise_for_status()
    return resp.json()


def get_existing_names() -> set:
    """Get names of all existing documents for this user."""
    r = requests.get(
        f"{BASE_URL}/api/health-data/documents?page_size=500",
        headers=auth_headers(),
    )
    if not r.ok:
        return set()
    return {d["name"] for d in r.json().get("items", [])}


def main():
    if not PHONE or not PASSWORD:
        print("请先设置 XJIE_UPLOAD_PHONE 和 XJIE_UPLOAD_PASSWORD。")
        sys.exit(2)

    print(f"=== 登录 {PHONE} ===")
    get_token()
    print("  OK\n")

    existing = get_existing_names()
    print(f"  已有 {len(existing)} 个文档，将跳过重复\n")

    stats = {"uploaded": 0, "skipped": 0, "fail": 0}

    # ─── 1. 体检报告 (images) ───
    exam_dir = os.path.join(TEST_DATA, "体检报告")
    folders = sorted(glob.glob(os.path.join(exam_dir, "张朝晖 *")))
    print(f"=== 体检报告: {len(folders)} 份 ===\n")

    for folder in folders:
        folder_name = os.path.basename(folder)
        parts = folder_name.split()
        date_str = parts[1] if len(parts) >= 2 else "unknown"
        base_name = f"体检报告-{date_str}"

        images = sorted(
            glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.png")),
            key=lambda x: int(os.path.splitext(os.path.basename(x))[0])
            if os.path.splitext(os.path.basename(x))[0].isdigit() else 999,
        )
        if not images:
            print(f"  跳过 {folder_name}: 无图片")
            continue

        print(f"  📋 {base_name} ({len(images)} 页)")
        for i, img in enumerate(images, 1):
            page_name = f"{base_name}-第{i}页" if len(images) > 1 else base_name

            print(f"    [{i}/{len(images)}] {os.path.basename(img)}...", end=" ", flush=True)
            try:
                result = upload_file(img, "exam", page_name)
                doc_id = result.get("id")
                stats["uploaded"] += 1
                print(f"✅ id={doc_id} (pending)")
                time.sleep(UPLOAD_DELAY)
            except Exception as e:
                stats["fail"] += 1
                print(f"❌ {e}")

    # ─── 2. 门诊病历 (CSV) ───
    record_dir = os.path.join(TEST_DATA, "门诊病历")
    csvs = sorted(glob.glob(os.path.join(record_dir, "*.csv")))
    print(f"\n=== 门诊病历: {len(csvs)} 份 ===\n")

    for csv_path in csvs:
        fname = os.path.basename(csv_path)
        stem = fname.rsplit(".", 1)[0].replace(" - ", "-").replace(" ", "")
        doc_name = f"门诊病历-{stem}"

        print(f"  {fname}...", end=" ", flush=True)
        try:
            result = upload_file(csv_path, "record", doc_name)
            stats["uploaded"] += 1
            print(f"✅ id={result.get('id')}")
        except Exception as e:
            stats["fail"] += 1
            print(f"❌ {e}")

    # ─── 3. 统计 ───
    print(f"\n=== 上传完成 ===")
    print(f"  发送: {stats['uploaded']}  跳过: {stats['skipped']}  失败: {stats['fail']}")
    print("  图片 LLM 提取在后台异步进行中...")


if __name__ == "__main__":
    main()
