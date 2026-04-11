"""
apply_thumbnails_fixed.py
--------------------------
A. 믹스 영상 썸네일을 원본(thumbnails/output/)으로 복원
C. 기존 Shorts 영상에 대응하는 믹스 썸네일 소급 적용

사용법:
    python apply_thumbnails_fixed.py --mode mix     # A: 믹스 원본 복원
    python apply_thumbnails_fixed.py --mode shorts  # C: Shorts 소급 적용
    python apply_thumbnails_fixed.py --mode all     # A + C 동시
    python apply_thumbnails_fixed.py --dry-run      # 미리보기
"""

import sys
import json
import pickle
import argparse
import time
import re
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

BASE_DIR      = Path(__file__).parent
BATCH_LOG     = BASE_DIR / "batch_log.json"
THUMB_DIR     = BASE_DIR / "thumbnails" / "output"       # 원본 영문 썸네일
THUMB_V2_DIR  = BASE_DIR / "thumbnails" / "output_v2"   # 감성 한글 썸네일
TOKEN_PATH    = BASE_DIR / "token.pickle"
CLIENT_SECRET = BASE_DIR / "client_secret.json"
SCOPES        = ["https://www.googleapis.com/auth/youtube"]

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
        print("[ERROR] batch_log.json 없음")
        sys.exit(1)
    with open(BATCH_LOG, "r", encoding="utf-8") as f:
        data = json.load(f)
    # list → dict 변환
    if isinstance(data, list):
        return {str(i): v for i, v in enumerate(data)}
    return data

# ── 썸네일 파일 탐색 ──────────────────────────────────────────────────────────
def find_original_thumb(batch_key: str) -> Path | None:
    """thumbnails/output/ 에서 배치 번호 매칭 썸네일 탐색"""
    candidates = list(THUMB_DIR.glob("*.jpg")) + list(THUMB_DIR.glob("*.png"))
    if not candidates:
        return None

    # batch 번호로 매칭
    num = int(batch_key) if batch_key.isdigit() else 0
    patterns = [f"batch{num:02d}", f"batch{num}", f"_{num:02d}", f"_{num}."]
    for p in patterns:
        matched = [f for f in candidates if p in f.name]
        if matched:
            return matched[0]

    # 폴백: 인덱스 순서
    if 0 <= num < len(candidates):
        return sorted(candidates)[num]
    return None

def find_mix_thumb_for_shorts(batch_key: str, batch_data: dict) -> Path | None:
    """Shorts에 적용할 믹스 썸네일 탐색 (원본 우선)"""
    # 1. batch_log의 thumbnail_path
    tp = batch_data.get("thumbnail_path", "")
    if tp and Path(tp).exists():
        return Path(tp)

    # 2. thumbnails/output/ 에서 탐색
    thumb = find_original_thumb(batch_key)
    if thumb:
        return thumb

    # 3. thumbnails/output_v2/ 에서 탐색
    v2 = THUMB_V2_DIR / f"thumb_v2_batch{batch_key}.jpg"
    if v2.exists():
        return v2

    return None

# ── YouTube 썸네일 적용 ────────────────────────────────────────────────────────
def set_thumbnail(youtube, video_id: str, thumb_path: Path, dry_run: bool) -> bool:
    if dry_run:
        print(f"    [DRY-RUN] {video_id} ← {thumb_path.name}")
        return True
    try:
        ext  = thumb_path.suffix.lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumb_path), mimetype=mime)
        ).execute()
        print(f"    ✅ 적용: {video_id} ← {thumb_path.name}")
        return True
    except Exception as e:
        print(f"    [ERROR] {video_id}: {e}")
        return False

# ── A: 믹스 영상 원본 썸네일 복원 ────────────────────────────────────────────
def restore_mix_thumbnails(youtube, log: dict, dry_run: bool):
    print("\n[A] 믹스 영상 원본 썸네일 복원")
    print(f"    소스: {THUMB_DIR}\n")

    success, fail, skip = [], [], []

    for key, val in log.items():
        if not isinstance(val, dict):
            continue
        video_id = val.get("video_id", "")
        if not video_id:
            continue

        mix_title = val.get("mix_title", f"Mix #{key}")
        print(f"  [배치 {key}] {mix_title}")

        thumb = find_original_thumb(key)
        if not thumb:
            print(f"    [SKIP] 원본 썸네일 없음")
            skip.append(key)
            continue

        ok = set_thumbnail(youtube, video_id, thumb, dry_run)
        if ok:
            success.append(key)
        else:
            fail.append(key)

        if not dry_run:
            time.sleep(2)

    print(f"\n  완료: {len(success)}개 / 스킵: {len(skip)}개 / 실패: {len(fail)}개")
    return success, fail

# ── C: Shorts 소급 썸네일 적용 ───────────────────────────────────────────────
def apply_shorts_thumbnails(youtube, log: dict, dry_run: bool):
    print("\n[C] Shorts 영상 믹스 썸네일 소급 적용\n")

    success, fail, skip = [], [], []

    for key, val in log.items():
        if not isinstance(val, dict):
            continue
        shorts_video_id = val.get("shorts_video_id", "")
        if not shorts_video_id or shorts_video_id == "DRY_RUN":
            continue

        mix_title = val.get("mix_title", f"Mix #{key}")
        print(f"  [배치 {key}] {mix_title}")
        print(f"    Shorts ID: {shorts_video_id}")

        thumb = find_mix_thumb_for_shorts(key, val)
        if not thumb:
            print(f"    [SKIP] 썸네일 없음")
            skip.append(key)
            continue

        ok = set_thumbnail(youtube, shorts_video_id, thumb, dry_run)
        if ok:
            success.append(key)
        else:
            fail.append(key)

        if not dry_run:
            time.sleep(2)

    print(f"\n  완료: {len(success)}개 / 스킵: {len(skip)}개 / 실패: {len(fail)}개")
    return success, fail

# ── 메인 ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",    choices=["mix", "shorts", "all"], default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("=" * 60)
    print("  apply_thumbnails_fixed.py")
    print("=" * 60)

    log     = load_batch_log()
    youtube = get_youtube()

    if args.mode in ("mix", "all"):
        restore_mix_thumbnails(youtube, log, args.dry_run)

    if args.mode in ("shorts", "all"):
        apply_shorts_thumbnails(youtube, log, args.dry_run)

    print("\n" + "=" * 60)
    print("  완료!")
    if args.dry_run:
        print("  실제 적용: --dry-run 제거 후 재실행")
    print("=" * 60)

if __name__ == "__main__":
    main()