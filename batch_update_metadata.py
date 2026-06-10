"""
batch_update_metadata.py  ·  J_Jlaylist  ·  v1
─────────────────────────────────────────────────────────
기존 영상 메타데이터 일괄 재생성 (옵션 B-2: 분산 일괄)

기능:
  1. YouTube에서 모든 영상 목록 + 현재 description/tags 조회
  2. metadata.py의 generate_metadata() 함수로 새 메타데이터 생성
  3. 우선순위 정렬: 비 오는 날 > 야경 > 퇴근 > 작업 > 일반
  4. 매일 20개씩 점진 적용 (분산 효과)
  5. 변경 전 description/tags 자동 백업 (롤백 가능)
  6. 진행 상태 추적 (metadata_progress.json)
  7. 이메일 보고용 구조화 출력

사용법:
  로컬:
    python batch_update_metadata.py --check           # 우선순위 미리보기
    python batch_update_metadata.py --preview --limit 3  # 3개만 새 메타데이터 미리보기
    python batch_update_metadata.py --apply --daily-limit 20  # 풀 적용
  
  자동화 (GitHub Actions):
    python batch_update_metadata.py --apply --auto --daily-limit 20
  
  롤백 (특정 영상):
    python batch_update_metadata.py --rollback VIDEO_ID
  
  롤백 (전체):
    python batch_update_metadata.py --rollback-all
"""

import os
import sys
import io
import json
import time
import pickle
import base64
import argparse
import re
from pathlib import Path
from datetime import datetime, timezone

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Windows CMD UTF-8 강제
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ── 경로 ──────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
TOKEN_FILE      = BASE_DIR / "token.pickle"
PROGRESS_FILE   = BASE_DIR / "metadata_progress.json"
BACKUP_DIR      = BASE_DIR / "backup_metadata"
LOG_FILE        = BASE_DIR / "metadata_update_log.json"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# ── 우선순위 키워드 (P0 → P3) ─────────────────────────────────────
PRIORITY_KEYWORDS = [
    # P0: AI가 발견한 최우선 (시청 유지율 3.6배)
    ("p0_rain", ["비 오", "비오는", "rain", "rainy", "빗속", "빗소리"]),
    # P1: 야경 시리즈 (P0와 연관, 시청자 패턴 강함)
    ("p1_night", ["야경", "tokyo night", "도쿄 나이트", "네온", "midnight"]),
    # P2: 퇴근/작업 (데스크탑 청자 직접 타겟)
    ("p2_work", ["퇴근", "작업", "야근", "새벽", "코딩", "재택"]),
    # P3: 카페/일상 (간접 타겟)
    ("p3_cafe", ["카페", "cafe", "혼자", "잔잔"]),
    # P4: 나머지
    ("p4_other", []),
]


# ── YouTube 인증 ─────────────────────────────────────────────────
def get_youtube():
    creds = None
    env_token = os.environ.get("TOKEN_PICKLE_B64")
    if env_token:
        creds = pickle.loads(base64.b64decode(env_token))
    elif TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    else:
        sys.exit("❌ token.pickle 없음")

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if not env_token and TOKEN_FILE.exists():
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


# ── 영상 목록 ───────────────────────────────────────────────────
def get_all_videos(yt):
    """모든 영상의 ID + title + description + tags + duration 조회"""
    ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    video_ids = []
    next_token = None
    while True:
        pl_resp = yt.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_token,
        ).execute()
        for it in pl_resp["items"]:
            video_ids.append(it["contentDetails"]["videoId"])
        next_token = pl_resp.get("nextPageToken")
        if not next_token:
            break

    videos = []
    seen = set()
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        v_resp = yt.videos().list(
            part="snippet,contentDetails,status",
            id=",".join(chunk),
        ).execute()
        for it in v_resp["items"]:
            if it["id"] in seen:
                continue
            seen.add(it["id"])
            snip = it["snippet"]
            videos.append({
                "id": it["id"],
                "title": snip.get("title", ""),
                "description": snip.get("description", ""),
                "tags": snip.get("tags", []),
                "category_id": snip.get("categoryId", "10"),
                "duration_iso": it["contentDetails"]["duration"],
                "is_shorts": _is_shorts(it["contentDetails"]["duration"]),
                "privacy": it["status"].get("privacyStatus", "public"),
                "published_at": snip.get("publishedAt", ""),
            })
    return videos


def _is_shorts(duration_iso):
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", duration_iso)
    if not m:
        return False
    mins = int(m.group(1) or 0)
    secs = int(m.group(2) or 0)
    return (mins * 60 + secs) <= 60


# ── 우선순위 분류 ────────────────────────────────────────────────
def classify_priority(title, description=""):
    """제목+설명에서 키워드 매칭으로 우선순위 결정"""
    text = (title + " " + description[:200]).lower()
    for prio_name, keywords in PRIORITY_KEYWORDS:
        if not keywords:
            continue
        for kw in keywords:
            if kw.lower() in text:
                return prio_name
    return "p4_other"


# ── mood 추출 (metadata.py 호출용) ──────────────────────────────
def extract_mood_from_title(title):
    """기존 제목에서 mood 추출 (대략적)"""
    title_lower = title.lower()
    if any(kw in title_lower for kw in ["비 오", "비오는", "rain", "rainy"]):
        return "비 오는 밤 창가에서 듣는 멜랑콜리한 무드"
    if any(kw in title_lower for kw in ["야경", "tokyo night", "도쿄 나이트", "네온"]):
        return "도쿄 야경을 보며 듣는 시티팝 무드"
    if any(kw in title_lower for kw in ["퇴근", "midnight", "자정"]):
        return "퇴근 후 야경을 보며 듣는 멜랑콜리한 무드"
    if any(kw in title_lower for kw in ["새벽", "dawn", "morning", "아침"]):
        return "새벽 감성의 잔잔한 시티팝 무드"
    if any(kw in title_lower for kw in ["카페", "cafe"]):
        return "비 오는 날 카페에서 작업하며 듣는 무드"
    if any(kw in title_lower for kw in ["80s", "80년대", "retro", "nostalgia"]):
        return "80년대 시티팝 노스탤지어 무드"
    if any(kw in title_lower for kw in ["lofi", "로파이"]):
        return "잔잔한 일본 로파이 무드"
    return "일본 시티팝 잔잔한 무드"


def extract_genre_from_title(title):
    title_lower = title.lower()
    if "lofi" in title_lower or "로파이" in title_lower:
        return "lofi"
    return "citypop"


def extract_duration_hours(duration_iso):
    """ISO 8601 duration → hours"""
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration_iso)
    if not m:
        return 0.5
    h = int(m.group(1) or 0)
    m_ = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return round((h * 3600 + m_ * 60 + s) / 3600, 2)


# ── 백업 ────────────────────────────────────────────────────────
def backup_metadata(video):
    """변경 전 description/tags 백업"""
    backup_file = BACKUP_DIR / f"{video['id']}.json"
    if backup_file.exists():
        return  # 이미 백업됨 (중복 호출 방지)
    backup_file.write_text(json.dumps({
        "id": video["id"],
        "title": video["title"],
        "description": video["description"],
        "tags": video["tags"],
        "category_id": video["category_id"],
        "backed_up_at": datetime.now(timezone.utc).isoformat(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# ── 메타데이터 업데이트 ─────────────────────────────────────────
def update_video_metadata(yt, video_id, new_title, new_description, new_tags, category_id="10"):
    """YouTube videos.update() 호출"""
    yt.videos().update(
        part="snippet",
        body={
            "id": video_id,
            "snippet": {
                "title": new_title,
                "description": new_description,
                "tags": new_tags,
                "categoryId": category_id,
            }
        }
    ).execute()


# ── 롤백 ────────────────────────────────────────────────────────
def rollback_video(yt, video_id):
    """백업에서 원본 메타데이터 복원"""
    backup_file = BACKUP_DIR / f"{video_id}.json"
    if not backup_file.exists():
        print(f"  ✗ 백업 없음: {video_id}")
        return False
    backup = json.loads(backup_file.read_text(encoding="utf-8"))
    try:
        update_video_metadata(
            yt, video_id,
            backup["title"],
            backup["description"],
            backup.get("tags", []),
            backup.get("category_id", "10"),
        )
        print(f"  ✓ 롤백 완료: {video_id}")
        return True
    except Exception as e:
        print(f"  ✗ 롤백 실패: {video_id} | {e}")
        return False


# ── 진행 상태 ───────────────────────────────────────────────────
def load_progress():
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
    return {"applied": [], "last_run": "", "rolled_back": []}


def save_progress(progress):
    PROGRESS_FILE.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    return {}


def save_log(log):
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


# ── main ─────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="우선순위 미리보기 (적용 X)")
    ap.add_argument("--preview", action="store_true", help="새 메타데이터 미리보기 (적용 X)")
    ap.add_argument("--apply", action="store_true", help="실제 적용")
    ap.add_argument("--daily-limit", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--rollback", type=str, default="", help="특정 영상 롤백 (video_id)")
    ap.add_argument("--rollback-all", action="store_true", help="전체 롤백")
    ap.add_argument("--auto", action="store_true", help="자동화 모드")
    ap.add_argument("--reset-progress", action="store_true", help="progress 초기화")
    args = ap.parse_args()

    if not any([args.check, args.preview, args.apply, args.rollback, args.rollback_all]):
        ap.print_help()
        sys.exit(0)

    if args.reset_progress:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
        print("⚠️ progress 초기화 완료")

    print(f"━━━ batch_update_metadata v1 ━━━\n")

    yt = get_youtube()

    # ── 롤백 모드 ──
    if args.rollback:
        print(f"[ROLLBACK] {args.rollback}")
        rollback_video(yt, args.rollback)
        progress = load_progress()
        if args.rollback in progress["applied"]:
            progress["applied"].remove(args.rollback)
            progress["rolled_back"].append(args.rollback)
            save_progress(progress)
        return

    if args.rollback_all:
        print("[ROLLBACK ALL]")
        progress = load_progress()
        applied = progress.get("applied", [])
        if not applied:
            print("  적용된 영상 없음. 롤백 불필요.")
            return
        print(f"  대상: {len(applied)}개")
        for vid in applied[:]:
            rollback_video(yt, vid)
            progress["applied"].remove(vid)
            progress["rolled_back"].append(vid)
            time.sleep(1)
        save_progress(progress)
        print(f"\n  완료: {len(applied)}개 롤백")
        return

    # ── 영상 목록 + 우선순위 분류 ──
    print("[1/3] YouTube 영상 목록 조회...")
    all_videos = get_all_videos(yt)
    print(f"  → 전체 {len(all_videos)}개\n")

    # 우선순위 분류 + 진행 상태 필터링
    progress = load_progress()
    applied_set = set(progress.get("applied", []))

    classified = {p[0]: [] for p in PRIORITY_KEYWORDS}
    for v in all_videos:
        if v["id"] in applied_set:
            continue
        # Shorts는 제외 (description/tags 변경 효과 약함)
        if v["is_shorts"]:
            continue
        prio = classify_priority(v["title"], v["description"])
        classified[prio].append(v)

    # 우선순위 정렬 + daily_limit 적용
    queue = []
    for prio_name, _ in PRIORITY_KEYWORDS:
        for v in classified[prio_name]:
            v["priority"] = prio_name
            queue.append(v)

    print(f"[2/3] 우선순위 분류 결과:")
    for prio_name, _ in PRIORITY_KEYWORDS:
        count = len([v for v in classified[prio_name]])
        if count > 0:
            print(f"  {prio_name}: {count}개")
    print(f"  ─────────────────")
    print(f"  미적용 대기: {len(queue)}개")
    print(f"  이미 적용:   {len(applied_set)}개")
    print(f"  전체 롱폼:   {len([v for v in all_videos if not v['is_shorts']])}개\n")

    # ── CHECK 모드 ──
    if args.check:
        print("[CHECK] 다음 처리 예정 (상위 20개):")
        for i, v in enumerate(queue[:20], 1):
            print(f"  [{i}] [{v['priority']}] {v['id']} | {v['title'][:60]}")
        return

    # ── PREVIEW/APPLY 모드 ──
    daily_limit = args.daily_limit if args.daily_limit > 0 else args.limit if args.limit > 0 else 20
    targets = queue[:daily_limit]

    if not targets:
        print("✓ 처리 대상 없음. 모든 영상 적용 완료.")
        if args.auto:
            print("\n::REPORT_START::")
            print(json.dumps({
                "applied_today": [],
                "total_applied": len(applied_set),
                "remaining": 0,
                "status": "ALL_DONE",
            }, ensure_ascii=False, indent=2))
            print("::REPORT_END::")
            print("::RESULT::ALL_DONE")
        return

    # metadata.py 임포트 (지연 임포트, 환경 안정성)
    try:
        from metadata import generate_metadata
    except Exception as e:
        print(f"❌ metadata.py 임포트 실패: {e}")
        sys.exit(1)

    print(f"[3/3] {'APPLY' if args.apply else 'PREVIEW'} 시작 — {len(targets)}개\n")

    log = load_log()
    applied_today = []
    success, fail = 0, 0

    for i, video in enumerate(targets, 1):
        vid = video["id"]
        title = video["title"]
        prio = video["priority"]

        try:
            print(f"[{i}/{len(targets)}] [{prio}] {vid} | {title[:50]}")

            # 1. mood + genre + duration 추출
            mood = extract_mood_from_title(title)
            genre = extract_genre_from_title(title)
            duration_hours = extract_duration_hours(video["duration_iso"])

            # 2. 새 메타데이터 생성
            print(f"        → Claude API 호출 중...")
            meta = generate_metadata(
                track_mood=mood,
                genre=genre,
                duration_hours=duration_hours,
            )

            if not meta:
                print(f"        ✗ 메타데이터 생성 실패 (None 반환)")
                fail += 1
                continue

            # 3. 새 title은 기존 title 유지 (변수 통제 - 시청자 인식 안정성)
            #    description/tags만 업데이트
            new_title = title  # 기존 유지
            new_description = meta.get("description", "")
            new_tags = meta.get("tags", [])[:15]  # YouTube 한도

            # 4. PREVIEW: 미리보기만
            if args.preview:
                print(f"        새 description 첫 200자:")
                print(f"        {new_description[:200]}...")
                print(f"        새 tags: {new_tags[:5]}... (총 {len(new_tags)}개)")
                success += 1
                continue

            # 5. APPLY: 백업 → 업데이트
            backup_metadata(video)  # 변경 전 백업
            update_video_metadata(
                yt, vid, new_title, new_description, new_tags,
                video["category_id"]
            )
            print(f"        ✓ 업데이트 완료")

            # 6. 진행 상태 저장
            applied_set.add(vid)
            progress["applied"] = sorted(applied_set)
            progress["last_run"] = datetime.now(timezone.utc).isoformat()
            save_progress(progress)

            log[vid] = {
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "priority": prio,
                "title": title,
                "tags_count": len(new_tags),
            }
            save_log(log)

            applied_today.append({
                "id": vid,
                "priority": prio,
                "title": title,
                "tags_preview": new_tags[:3],
            })

            success += 1
            time.sleep(3.0)  # API 안전 마진

        except HttpError as e:
            err_str = str(e)
            if "quotaExceeded" in err_str:
                print(f"        🛑 YouTube API 쿼터 초과. 중단.")
                break
            print(f"        ✗ API 실패: {e}")
            fail += 1
        except Exception as e:
            print(f"        ✗ 실패: {e}")
            fail += 1

    # ── 보고 ──
    remaining = len([v for v in queue if v["id"] not in applied_set])
    eta_days = max(1, (remaining + daily_limit - 1) // daily_limit) if remaining > 0 else 0

    print(f"\n━━━ 완료 ━━━")
    print(f"  성공:      {success}")
    print(f"  실패:      {fail}")
    print(f"  누적 적용: {len(applied_set)}개")
    print(f"  남은 영상: {remaining}개")
    print(f"  예상 완료: D+{eta_days}일")

    if args.auto:
        print("\n::REPORT_START::")
        print(json.dumps({
            "date": datetime.now(timezone.utc).isoformat(),
            "applied_today": applied_today,
            "success": success,
            "fail": fail,
            "total_applied": len(applied_set),
            "remaining": remaining,
            "eta_days": eta_days,
        }, ensure_ascii=False, indent=2))
        print("::REPORT_END::")

        if fail > 0 and success == 0:
            print("::RESULT::FAIL")
            sys.exit(1)
        if remaining == 0:
            print("::RESULT::ALL_DONE")
        else:
            print(f"::RESULT::SUCCESS::{success}")


if __name__ == "__main__":
    main()