#!/usr/bin/env python3
"""Batch upload test_data for user 张朝晖 via API.

Usage:
    python3 test_data/upload_all.py

Uploads:
  1. Each 体检报告 folder → one exam document per IMAGE (multi-page)
  2. Each 门诊病历 CSV → one record document
"""

import os
import sys
import time
import json
import glob
import requests

BASE_URL = "http://8.130.213.44:8000"
PHONE = "13800000001"
PASSWORD = "Test1234!"
TEST_DATA = os.path.join(os.path.dirname(__file__))

# Token management
_token_cache = {"token": None, "ts": 0}

def get_token() -> str:
    """Get a valid token, refreshing if older than 20 minutes."""
    if _token_cache["token"] and (time.time() - _token_cache["ts"]) < 1200:
        return _token_cache["token"]
    r = requests.post(f"{BASE_URL}/api/auth/login", json={
        "phone": PHONE, "password": PASSWORD
    })
    r.raise_for_status()
    _token_cache["token"] = r.json()["access_token"]
    _token_cache["ts"] = time.time()
    print(f"  [token refreshed]")
    return _token_cache["token"]


def login() -> str:
    return get_token()


def upload_file(filepath: str, doc_type: str, name: str) -> dict:
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}
    with open(filepath, "rb") as f:
        resp = requests.post(
            f"{BASE_URL}/api/health-data/upload",
            headers=headers,
            files={"file": (os.path.basename(filepath), f)},
            data={"doc_type": doc_type, "name": name},
            timeout=180,
        )
    resp.raise_for_status()
    return resp.json()


def main():
    resume_from = None
    if len(sys.argv) > 1 and sys.argv[1] == "--resume":
        resume_from = sys.argv[2] if len(sys.argv) > 2 else None

    print("=== 登录 ===")
    token = login()
    print(f"Token: {token[:30]}...")

    if not resume_from:
        # 删除已有文档（清理之前的测试数据）
        headers = {"Authorization": f"Bearer {token}"}
        existing = requests.get(f"{BASE_URL}/api/health-data/documents", headers=headers).json()
        for item in existing.get("items", []):
            print(f"  删除旧文档: {item['name']} (id={item['id']})")
            requests.delete(f"{BASE_URL}/api/health-data/documents/{item['id']}", headers=headers)

    # ─── 1. 上传体检报告 ───
    exam_dir = os.path.join(TEST_DATA, "体检报告")
    exam_folders = sorted(glob.glob(os.path.join(exam_dir, "张朝晖 *")))
    print(f"\n=== 上传体检报告 ({len(exam_folders)} 份) ===")

    started = not resume_from  # if no resume, start immediately
    for folder in exam_folders:
        folder_name = os.path.basename(folder)
        # Extract date from folder name: "张朝晖 2025-06-16 体检报告"
        parts = folder_name.split()
        date_str = parts[1] if len(parts) >= 2 else "unknown"
        doc_name = f"张朝晖-{date_str}-体检报告"

        if not started:
            if date_str == resume_from or folder_name == resume_from:
                started = True
            else:
                print(f"  跳过 {doc_name} (resume)")
                continue

        images = sorted(
            glob.glob(os.path.join(folder, "*.jpg")) + glob.glob(os.path.join(folder, "*.png")),
            key=lambda x: int(os.path.splitext(os.path.basename(x))[0]) if os.path.splitext(os.path.basename(x))[0].isdigit() else 999
        )
        
        if not images:
            print(f"  跳过 {folder_name}: 无图片")
            continue

        print(f"\n  📋 {doc_name} ({len(images)} 页)")
        
        # Upload each image as a separate document (with same name prefix + page number)
        for i, img_path in enumerate(images, 1):
            page_name = f"{doc_name}-第{i}页" if len(images) > 1 else doc_name
            print(f"    上传第 {i}/{len(images)} 页: {os.path.basename(img_path)}...", end=" ", flush=True)
            
            t0 = time.time()
            try:
                result = upload_file(img_path, "exam", page_name)
                elapsed = time.time() - t0
                rows = result.get("csv_data", {}).get("rows", [])
                abnormals = result.get("abnormal_flags", [])
                print(f"✅ ({elapsed:.1f}s) {len(rows)}项, {len(abnormals)}异常")
            except Exception as e:
                elapsed = time.time() - t0
                print(f"❌ ({elapsed:.1f}s) {e}")

    # ─── 2. 上传门诊病历 CSV ───
    record_dir = os.path.join(TEST_DATA, "门诊病历")
    csvs = sorted(glob.glob(os.path.join(record_dir, "*.csv")))
    print(f"\n=== 上传门诊病历 ({len(csvs)} 份) ===")

    for csv_path in csvs:
        fname = os.path.basename(csv_path)
        # "张朝晖 - 2024-07-25.csv" → "张朝晖-2024-07-25-病例"
        stem = fname.rsplit(".", 1)[0].replace(" - ", "-").replace(" ", "")
        doc_name = f"{stem}-病例"
        
        print(f"  上传 {fname}...", end=" ", flush=True)
        t0 = time.time()
        try:
            result = upload_file(csv_path, "record", doc_name)
            elapsed = time.time() - t0
            rows = result.get("csv_data", {}).get("rows", [])
            print(f"✅ ({elapsed:.1f}s) {len(rows)}项")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"❌ ({elapsed:.1f}s) {e}")

    # ─── 3. 统计 ───
    print("\n=== 上传完成，统计 ===")
    headers_final = {"Authorization": f"Bearer {get_token()}"}
    docs = requests.get(f"{BASE_URL}/api/health-data/documents", headers=headers_final).json()
    total = docs.get("total", 0)
    exams = sum(1 for d in docs.get("items", []) if d["doc_type"] == "exam")
    records = sum(1 for d in docs.get("items", []) if d["doc_type"] == "record")
    print(f"  总计: {total} 文档 (体检报告: {exams}, 门诊病历: {records})")


if __name__ == "__main__":
    main()
