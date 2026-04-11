"""
shorts_cleanup.py
------------------
YouTube Shorts 중복 영상 탐지 + 삭제 + batch_log 정리

전략:
- 같은 날짜에 같은 패턴(#번호) Shorts가 2개 이상이면 중복으로 판단
- 감성형 제목(새벽/비 오는/혼자/아련 등) 우선 유지
- 원본 기계형 제목(JAPANESE CITY POP MIX #XX) 삭제

사용법:
    python shorts_cleanup.py --dry-run     # 중복 탐지만 (삭제 안 함)
    python shorts_cleanup.py               # 실제 삭제
"""

import sys
import json
import pickle
import argparse
import re
import time
from pathlib import Path
from datetime import datetime

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

BASE_DIR      = Path(__file__).parent
BATCH_LOG     = BASE_DIR / "batch_log.json"
TOKEN_PATH    = BASE_DIR / "token.pickle"
CLIENT_SECRET = BASE_DIR / "client_secret.json"
SCOPES        = ["https://www.googleapis.com/auth/youtube"]

# ── 감성형 제목 키워드 ─────────────────────────────────────────────────────────
EMOTIONAL_KEYWORDS = [
    "새벽", "비 오는", "혼자", "아련", "몽환", "포근", "잔잔",
    "고요", "도쿄 새벽", "나른한", "감성", "자정"
]

# ── 인증 ──────────────────────────────────────────────────────────────────────
def get_youtube():
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)

# ── batch_log 로드 ─────────────────────────────────────────────────────────────
def load_batch_log() -> dict:
    if not BATCH_LOG.exists():
        return {}
    with open(BATCH_LOG, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {str(i): v for i, v in enumerate(data)}
    return data

def save_batch_log(log: dict):
    with open(BATCH_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ── 내 채널 Shorts 전체 가져오기 ──────────────────────────────────────────────
def get_all_shorts(youtube) -> list[dict]:
    # 업로드 플레이리스트 ID
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos, next_page = [], None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_page
        ).execute()

        for item in resp.get("items", []):
            sn = item["snippet"]
            video_id = sn["resourceId"]["videoId"]
            title    = sn.get("title", "")
            published = sn.get("publishedAt", "")
            videos.append({
                "video_id":  video_id,
                "title":     title,
                "published": published,
            })

        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    # Shorts만 필터 (제목에 #Shorts 포함 또는 59초 이하 — 여기선 제목 기준)
    shorts = [v for v in videos if "#Shorts" in v["title"] or "#shorts" in v["title"]]
    return shorts

# ── 제목에서 믹스 번호 추출 ────────────────────────────────────────────────────
def extract_mix_number(title: str) -> str | None:
    m = re.search(r"#(\d+)", title)
    if m:
        return m.group(1).zfill(2)
    if "TOKYO NIGHT DRIVE" in title.upper():
        return "TOKYO"
    return None

# ── 감성형 제목인지 판단 ───────────────────────────────────────────────────────
def is_emotional(title: str) -> bool:
    return any(kw in title for kw in EMOTIONAL_KEYWORDS)

# ── 중복 탐지 ──────────────────────────────────────────────────────────────────
def find_duplicates(shorts: list[dict]) -> list[dict]:
    """
    같은 믹스 번호의 Shorts가 2개 이상이면 중복
    감성형 제목을 유지하고 나머지를 삭제 대상으로 반환
    """
    from collections import defaultdict
    groups = defaultdict(list)

    for s in shorts:
        num = extract_mix_number(s["title"])
        if num:
            groups[num].append(s)

    to_delete = []
    to_keep   = []

    for num, group in groups.items():
        if len(group) <= 1:
            to_keep.extend(group)
            continue

        # 감성형 우선 유지
        emotional = [s for s in group if is_emotional(s["title"])]
        mechanical = [s for s in group if not is_emotional(s["title"])]

        if emotional:
            keep   = emotional[0]
            delete = mechanical + emotional[1:]  # 감성형 중복도 제거
        else:
            keep   = group[0]
            delete = group[1:]

        to_keep.append(keep)
        to_delete.extend(delete)

    return to_delete, to_keep

# ── YouTube 영상 삭제 ──────────────────────────────────────────────────────────
def delete_video(youtube, video_id: str, dry_run: bool) -> bool:
    if dry_run:
        return True
    try:
        youtube.videos().delete(id=video_id).execute()
        return True
    except Exception as e:
        print(f"  [ERROR] 삭제 실패 {video_id}: {e}")
        return False

# ── batch_log에서 삭제된 video_id 정리 ────────────────────────────────────────
def cleanup_batch_log(deleted_ids: list[str]):
    log = load_batch_log()
    changed = False
    for key, val in log.items():
        if not isinstance(val, dict):
            continue
        if val.get("shorts_video_id") in deleted_ids:
            val.pop("shorts_video_id", None)
            val.pop("shorts_video_id_path", None)
            val.pop("shorts_publish_at", None)
            val.pop("shorts_title", None)
            changed = True
            print(f"  [LOG] 배치 {key} shorts_video_id 초기화")
    if changed:
        save_batch_log(log)

# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Shorts 중복 탐지 + 삭제")
    parser.add_argument("--dry-run", action="store_true", help="탐지만 (삭제 안 함)")
    args = parser.parse_args()

    print("=" * 60)
    print("  shorts_cleanup.py  —  Shorts 중복 정리")
    print("=" * 60)

    youtube = get_youtube()

    print("\n채널 Shorts 목록 가져오는 중...")
    shorts = get_all_shorts(youtube)
    print(f"총 {len(shorts)}개 Shorts 확인\n")

    to_delete, to_keep = find_duplicates(shorts)

    # ── 유지 목록 출력 ─────────────────────────────────────────────────────────
    print(f"[유지] {len(to_keep)}개:")
    for s in sorted(to_keep, key=lambda x: x["title"]):
        print(f"  ✅ {s['title'][:60]}")
        print(f"     {s['video_id']}")

    print(f"\n[삭제 대상] {len(to_delete)}개:")
    for s in sorted(to_delete, key=lambda x: x["title"]):
        print(f"  ❌ {s['title'][:60]}")
        print(f"     {s['video_id']}")

    if not to_delete:
        print("\n중복 없음! 정리 불필요.")
        return

    if args.dry_run:
        print(f"\n[DRY-RUN] 실제 삭제 안 함 — --dry-run 제거 후 재실행")
        return

    # ── 실제 삭제 ─────────────────────────────────────────────────────────────
    print(f"\n삭제 시작...")
    deleted_ids = []
    for s in to_delete:
        ok = delete_video(youtube, s["video_id"], args.dry_run)
        if ok:
            print(f"  🗑️  삭제: {s['title'][:50]}")
            deleted_ids.append(s["video_id"])
        time.sleep(1)

    # batch_log 정리
    if deleted_ids:
        print(f"\nbatch_log 정리 중...")
        cleanup_batch_log(deleted_ids)

    print("\n" + "=" * 60)
    print(f"  삭제 완료: {len(deleted_ids)}개")
    print(f"  유지: {len(to_keep)}개")
    print("=" * 60)

if __name__ == "__main__":
    main()