"""
shorts_uploader.py
-------------------
output/shorts/ 의 *_shorts.mp4 → YouTube Shorts 자동 업로드
기존 token.pickle / client_secret.json 재사용

사용법:
    python shorts_uploader.py               # 전체 업로드
    python shorts_uploader.py --batch 3     # 배치 3번만
    python shorts_uploader.py --dry-run     # 업로드 없이 미리보기
    python shorts_uploader.py --interval 2  # 업로드 간격 일수 (기본 2일)
    python shorts_uploader.py --hour 18     # 공개 시간 KST (기본 18시)

YouTube Shorts 조건:
    - 세로 9:16 (이미 shorts_generator가 처리)
    - 60초 이하 (58초로 생성됨)
    - 제목에 #Shorts 포함 OR 설명에 #Shorts 포함
"""

import os
import json
import pickle
import argparse
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

import anthropic

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
SHORTS_DIR      = BASE_DIR / "output" / "shorts"
BATCH_LOG       = BASE_DIR / "batch_log.json"
TOKEN_PATH      = BASE_DIR / "token.pickle"
CLIENT_SECRET   = BASE_DIR / "client_secret.json"

SCOPES = ["https://www.googleapis.com/auth/youtube"]

# ── 업로드 스케줄 기본값 ───────────────────────────────────────────────────────
DEFAULT_HOUR     = 18     # KST 18:00 (Shorts 황금 시간대)
DEFAULT_INTERVAL = 2      # 2일 간격

# ── YouTube 인증 ───────────────────────────────────────────────────────────────
def get_youtube_client():
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
        return json.load(f)

def save_batch_log(log: dict):
    with open(BATCH_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ── 처리 대상 Shorts 파일 탐색 ────────────────────────────────────────────────
def find_shorts_to_upload(batch_num: int | None) -> list[Path]:
    if not SHORTS_DIR.exists():
        print(f"[ERROR] output/shorts/ 없음 → 먼저 shorts_generator.py 실행")
        return []

    all_files = sorted(SHORTS_DIR.glob("*_shorts.mp4"))
    log       = load_batch_log()

    # batch_log가 list인 경우 dict로 변환
    if isinstance(log, list):
        log = {str(i): v for i, v in enumerate(log)}

    # 이미 업로드된 파일 필터링
    uploaded_paths = {
        v.get("shorts_video_id_path")
        for v in log.values()
        if isinstance(v, dict) and v.get("shorts_video_id")
    }
    
    if batch_num is not None:
        patterns = [f"#{batch_num:02d}", f"#{batch_num}", f"_{batch_num:02d}"]
        all_files = [f for f in all_files if any(p in f.name for p in patterns)]

    pending = [f for f in all_files if str(f) not in uploaded_paths]
    return pending

# ── Claude API: Shorts 제목 + 설명 생성 ───────────────────────────────────────
def generate_shorts_metadata(filename: str, mix_title: str) -> dict:
    client = anthropic.Anthropic()

    stem = Path(filename).stem.replace("_shorts", "").replace("_", " ")

    prompt = f"""YouTube Shorts 메타데이터를 JSON으로 작성해주세요.

믹스 정보:
- 파일명 테마: {stem}
- 원본 믹스 제목: {mix_title}

규칙:
1. title: 감성적 한국어 + #Shorts 포함, 60자 이내
   예시: "🌙 한밤의 시티팝 드라이브 🎵 #Shorts #citypop"
2. description: 2-3줄 감성 소개 + #Shorts #citypop #lofi #일본감성 해시태그
3. tags: ["Shorts", "citypop", "lofi", "일본감성", "시티팝", "공부음악", "감성음악"] 형태 배열

반드시 아래 JSON 형식만 출력 (코드 펜스 없음):
{{"title": "...", "description": "...", "tags": [...]}}"""

    try:
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        text = resp.content[0].text.strip()
        # 마크다운 펜스 제거
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"  [WARN] Claude API 실패: {e} → 기본 메타데이터 사용")
        return {
            "title":       f"🌙 {stem} | Japanese City Pop Lofi Mix #Shorts",
            "description": f"Japanese City Pop & Lofi AI Music Mix 🎵\n\n#Shorts #citypop #lofi #일본감성 #시티팝",
            "tags":        ["Shorts", "citypop", "lofi", "시티팝", "일본감성", "공부음악"]
        }

# ── 예약 시간 생성 (KST → UTC RFC3339) ───────────────────────────────────────
def make_publish_time(offset_days: int, hour_kst: int) -> str:
    kst = timezone(timedelta(hours=18))
    now = datetime.now(kst)
    publish_kst = now.replace(hour=hour_kst, minute=0, second=0, microsecond=0)
    publish_kst += timedelta(days=offset_days)
    publish_utc = publish_kst.astimezone(timezone.utc)
    return publish_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")

# ── YouTube Shorts 업로드 ──────────────────────────────────────────────────────
def find_thumbnail_for_shorts(shorts_path: Path) -> Path | None:
    """Shorts 파일명에서 대응하는 썸네일 탐색"""
    # batch_log에서 썸네일 경로 찾기
    log = load_batch_log()
    if isinstance(log, list):
        log = {str(i): v for i, v in enumerate(log)}

    for v in log.values():
        if not isinstance(v, dict):
            continue
        sp = v.get("shorts_path", "")
        if sp and Path(sp).name == shorts_path.name:
            thumb = v.get("thumbnail_path", "")
            if thumb and Path(thumb).exists():
                return Path(thumb)

    # 폴백: thumbnails/output/ 에서 파일명 패턴 매칭
    # "JAPANESE CITY POP MIX #01_shorts.mp4" → "#01" 추출
    import re
    m = re.search(r"#(\d+)", shorts_path.stem)
    if m:
        num = m.group(1)
        thumb_dir = BASE_DIR / "thumbnails" / "output"
        candidates = list(thumb_dir.glob(f"*{num}*"))
        if candidates:
            return candidates[0]

    return None


def set_thumbnail(youtube, video_id: str, thumb_path: Path):
    """YouTube 썸네일 설정"""
    from googleapiclient.http import MediaFileUpload as MFU
    ext = thumb_path.suffix.lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MFU(str(thumb_path), mimetype=mime)
        ).execute()
        print(f"  🖼️  썸네일 적용: {thumb_path.name}")
    except Exception as e:
        print(f"  [WARN] 썸네일 설정 실패: {e}")
def upload_shorts(
    youtube,
    file_path: Path,
    metadata: dict,
    publish_at: str,
    dry_run: bool = False
) -> str | None:
    """
    Returns video_id on success, None on failure
    """
    if dry_run:
        print(f"  [DRY-RUN] 업로드 건너뜀")
        print(f"    제목: {metadata['title']}")
        print(f"    예약: {publish_at}")
        return "DRY_RUN"

    body = {
        "snippet": {
            "title":       metadata["title"],
            "description": metadata["description"],
            "tags":        metadata["tags"],
            "categoryId":  "10",           # Music
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus":          "private",   # 예약 → private 필수
            "publishAt":              publish_at,
            "selfDeclaredMadeForKids": False,
        }
    }

    media = MediaFileUpload(
        str(file_path),
        mimetype="video/mp4",
        resumable=True,
        chunksize=5 * 1024 * 1024   # 5MB 청크
    )

    try:
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        )

        print(f"  [업로드 중] {file_path.name}")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"    {pct}%", end="\r")

        video_id = response.get("id")
        print(f"  ✅ 완료: https://youtube.com/shorts/{video_id}")
        thumb_path = find_thumbnail_for_shorts(file_path)
        if thumb_path:
            set_thumbnail(youtube, video_id, thumb_path)

        return video_id
        print(f"     예약: {publish_at}")
        return video_id

    except Exception as e:
        print(f"  [ERROR] 업로드 실패: {e}")
        return None

# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Shorts MP4 → YouTube Shorts 자동 업로드"
    )
    parser.add_argument("--batch",    type=int,  default=None)
    parser.add_argument("--dry-run",  action="store_true",
                        help="실제 업로드 없이 미리보기")
    parser.add_argument("--interval", type=int,  default=DEFAULT_INTERVAL,
                        help=f"업로드 간격 일수 (기본: {DEFAULT_INTERVAL})")
    parser.add_argument("--hour",     type=int,  default=DEFAULT_HOUR,
                        help=f"공개 시간 KST (기본: {DEFAULT_HOUR}시)")
    parser.add_argument("--start-days", type=int, default=1,
                        help="첫 업로드까지 대기 일수 (기본: 1일 후)")
    args = parser.parse_args()

    print("=" * 60)
    print("  shorts_uploader.py  —  YouTube Shorts 자동 업로드")
    print("=" * 60)

    pending = find_shorts_to_upload(args.batch)
    if not pending:
        print("\n[INFO] 업로드할 Shorts 없음 (이미 전부 완료됐거나 파일 없음)")
        sys.exit(0)

    print(f"\n업로드 대상: {len(pending)}개\n")

    log     = load_batch_log()
    if isinstance(log, list):          # ← 이 두 줄 추가
        log = {str(i): v for i, v in enumerate(log)}
    youtube = None if args.dry_run else get_youtube_client()

    success, fail = [], []

    for i, shorts_file in enumerate(pending):
        print(f"[{i+1}/{len(pending)}] {shorts_file.name}")

        # 배치 키 찾기 (파일명에서 #번호 추출)
        batch_key = None
        for k, v in log.items():
            sp = v.get("shorts_path", "")
            if sp and Path(sp).name == shorts_file.name:
                batch_key = k
                break

        mix_title = log.get(batch_key or "", {}).get("mix_title", shorts_file.stem)

        # 메타데이터 생성
        print("  → Claude API 메타데이터 생성 중...")
        metadata = generate_shorts_metadata(shorts_file.name, mix_title)

        # 예약 시간
        publish_at = make_publish_time(args.start_days + i * args.interval, args.hour)

        # 업로드
        video_id = upload_shorts(youtube, shorts_file, metadata, publish_at, args.dry_run)

        if video_id:
            success.append(shorts_file.name)
            # batch_log 업데이트
            if batch_key and batch_key in log:
                log[batch_key]["shorts_video_id"]      = video_id
                log[batch_key]["shorts_video_id_path"] = str(shorts_file)
                log[batch_key]["shorts_publish_at"]    = publish_at
                log[batch_key]["shorts_title"]         = metadata["title"]
                save_batch_log(log)
        else:
            fail.append(shorts_file.name)

        # API 레이트리밋 방지
        if not args.dry_run and i < len(pending) - 1:
            print("  (3초 대기...)")
            time.sleep(3)

    # ── 결과 요약 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  완료: {len(success)}개  /  실패: {len(fail)}개")
    if success:
        print(f"\n  업로드된 Shorts:")
        for name in success:
            print(f"    ✅ {name}")
    if fail:
        print(f"\n  실패:")
        for name in fail:
            print(f"    ❌ {name}")
    print(f"\n  YouTube Studio → 콘텐츠 → Shorts 탭에서 확인하세요")
    print("=" * 60)

if __name__ == "__main__":
     main()