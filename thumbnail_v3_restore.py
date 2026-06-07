"""
thumbnail_v3_restore.py  ·  J_Jlaylist  ·  v2 (자동화 대응)
────────────────────────────────────────────────────────────────
v3 디자인 복원 + 일일 분산 적용 + GitHub Actions 자동화

신규 기능 (v2):
  - --daily-limit N: 하루 최대 N개만 적용
  - progress.json: 적용 완료 영상 ID 누적 기록
  - 429 에러 즉시 중단 (rate limit 카운터 누적 방지)
  - 자동화 모드 (--auto): GitHub Actions용 종료 코드/구조화 출력
  - Windows CMD UTF-8 강제

사용법:
  로컬:
    python thumbnail_v3_restore.py --check
    python thumbnail_v3_restore.py --preview --limit 3
    python thumbnail_v3_restore.py --apply --daily-limit 6
    python thumbnail_v3_restore.py --apply --shorts-only --daily-limit 6

  자동화 (GitHub Actions):
    python thumbnail_v3_restore.py --apply --auto --daily-limit 6
"""

import os
import sys
import io
import json
import time
import pickle
import random
import re
import argparse
import base64
from pathlib import Path
from datetime import datetime, timezone
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

# ── Windows CMD UTF-8 강제 ───────────────────────────────────────────────
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ── 경로 ─────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
BG_DIR        = BASE_DIR / "thumbnails" / "backgrounds"
OUT_DIR       = BASE_DIR / "thumbnails" / "output_v3"
BACKUP_DIR    = BASE_DIR / "thumbnails" / "backup_v51"
TOKEN_FILE    = BASE_DIR / "token.pickle"
LOG_FILE      = BASE_DIR / "thumbnail_v3_log.json"
PROGRESS_FILE = BASE_DIR / "thumbnail_v3_progress.json"
FONT_DIR      = BASE_DIR / "fonts"

OUT_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

W, H = 1280, 720
SCOPES = ["https://www.googleapis.com/auth/youtube"]


# ── mood 분류 키워드 ─────────────────────────────────────────────────────
MOOD_KEYWORDS = {
    "cafe_rain":      ["rain", "비 오", "비오는", "빗속", "빗소리", "카페", "cafe", "창문", "창밖", "rainy"],
    "dawn_morning":   ["dawn", "새벽", "아침", "morning", "sunrise", "여명", "해뜨", "새벽시", "새벽 2시", "이른 아침"],
    "midnight_drive": ["midnight", "자정", "드라이브", "drive", "퇴근", "고속도로", "한밤", "심야", "야근"],
    "melancholy":     ["혼자", "고요", "쓸쓸", "잔잔", "나른", "몽환", "포근", "감성", "아련", "nostalgia"],
    "night_drive":    ["네온사인", "tokyo night", "도쿄 나이트", "네온 불빛", "나이트 드라이브"],
    "neon_city":      ["neon", "shibuya", "신주쿠", "도시", "네온"],
}
DEFAULT_MOOD = "night_drive"

MOOD_EN_LABELS = {
    "night_drive":    ["TOKYO NIGHT", "CITY POP NIGHT", "JAPANESE CITY POP", "NEON CITY POP"],
    "midnight_drive": ["MIDNIGHT DRIVE", "TOKYO DRIVE", "HIGHWAY CITY POP", "NIGHT DRIVE"],
    "neon_city":      ["NEON CITY", "TOKYO NEON", "URBAN CITY POP", "SHIBUYA LIGHTS"],
    "cafe_rain":      ["CITY POP RAIN", "LOFI CITY POP", "CAFE CITY POP", "RAINY CITY POP"],
    "melancholy":     ["JAPANESE LOFI", "QUIET CITY POP", "80S CITY POP", "CITY POP NOSTALGIA"],
    "dawn_morning":   ["DAWN CITY POP", "MORNING CITY POP", "SUNRISE LOFI", "EARLY CITY POP"],
}


# ── YouTube OAuth (로컬 + GitHub Actions 양쪽 지원) ──────────────────────
def get_youtube():
    creds = None
    env_token = os.environ.get("TOKEN_PICKLE_B64")
    if env_token:
        creds = pickle.loads(base64.b64decode(env_token))
    elif TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    else:
        sys.exit("❌ token.pickle 없음 (파일 또는 TOKEN_PICKLE_B64 env)")

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if not env_token and TOKEN_FILE.exists():
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


# ── 영상 목록 ───────────────────────────────────────────────────────────
def get_all_videos(yt):
    ch_resp = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos = []
    next_token = None
    while True:
        pl_resp = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_token,
        ).execute()
        for it in pl_resp["items"]:
            videos.append({
                "id": it["contentDetails"]["videoId"],
                "title": it["snippet"]["title"],
                "published_at": it["contentDetails"].get("videoPublishedAt", ""),
            })
        next_token = pl_resp.get("nextPageToken")
        if not next_token:
            break

    enriched = []
    seen = set()
    for i in range(0, len(videos), 50):
        chunk = videos[i:i + 50]
        ids = ",".join(v["id"] for v in chunk)
        v_resp = yt.videos().list(part="contentDetails,status", id=ids).execute()
        info = {it["id"]: it for it in v_resp["items"]}
        for v in chunk:
            if v["id"] in seen:
                continue
            seen.add(v["id"])
            d = info.get(v["id"])
            if not d:
                continue
            dur = d["contentDetails"]["duration"]
            v["duration_iso"] = dur
            v["is_shorts"] = _is_shorts(dur)
            v["privacy"] = d["status"].get("privacyStatus", "")
            enriched.append(v)
    return enriched


def _is_shorts(duration_iso):
    m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", duration_iso)
    if not m:
        return False
    mins = int(m.group(1) or 0)
    secs = int(m.group(2) or 0)
    return (mins * 60 + secs) <= 60


# ── mood/배경/텍스트 ──────────────────────────────────────────────────────
def classify_mood(title):
    tl = title.lower()
    scores = {m: sum(1 for kw in kws if kw.lower() in tl)
              for m, kws in MOOD_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else DEFAULT_MOOD


def pick_background(mood, seed):
    rng = random.Random(seed)
    exts = ["*.jpg", "*.jpeg", "*.png", "*.webp"]
    mood_dir = BG_DIR / mood
    if mood_dir.exists():
        imgs = [f for ext in exts for f in mood_dir.glob(ext)]
        if imgs:
            return rng.choice(imgs)
    all_imgs = [f for ext in exts for f in BG_DIR.rglob(ext)]
    return rng.choice(all_imgs) if all_imgs else None


def pick_en_text(title, mood, seed):
    rng = random.Random(seed)
    year_m = re.search(r"(70|80|90)s?", title, re.IGNORECASE)
    if year_m:
        decade = year_m.group(0).upper().rstrip("S") + "S"
        return f"{decade} CITY POP"
    pool = MOOD_EN_LABELS.get(mood, ["CITY POP LOFI"])
    return rng.choice(pool)


# ── 폰트 (Win + Ubuntu) ──────────────────────────────────────────────────
def load_font(size):
    candidates = []
    if FONT_DIR.exists():
        candidates += list(FONT_DIR.glob("*.ttf")) + list(FONT_DIR.glob("*.otf"))
    candidates += [
        Path("C:/Windows/Fonts/Impact.ttf"),
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("C:/Windows/Fonts/Arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ]
    for c in candidates:
        if c.exists():
            try:
                return ImageFont.truetype(str(c), size)
            except Exception:
                continue
    return ImageFont.load_default()


# ── 배경 가공 + 합성 ─────────────────────────────────────────────────────
def prepare_bg(bg_path, seed):
    bg = Image.open(bg_path).convert("RGB")
    bw, bh = bg.size
    tr = W / H
    br = bw / bh
    if br > tr:
        nh = bh
        nw = int(bh * tr)
    else:
        nw = bw
        nh = int(bw / tr)
    rng = random.Random(seed)
    left = rng.randint(0, max(0, bw - nw))
    top = rng.randint(0, max(0, int((bh - nh) * 0.4)))
    bg = bg.crop((left, top, left + nw, top + nh))
    bg = bg.resize((W, H), Image.LANCZOS)
    bg = ImageEnhance.Color(bg).enhance(1.2)
    bg = ImageEnhance.Contrast(bg).enhance(1.1)
    return bg


def render_thumbnail(canvas, en_text):
    canvas = canvas.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    en_text = en_text.replace("\n", " ").strip()

    target_w = int(W * 0.60)
    size = 130
    font = load_font(size)
    bbox = draw.textbbox((0, 0), en_text, font=font)
    text_w = bbox[2] - bbox[0]
    while text_w < target_w and size < 200:
        size += 5
        font = load_font(size)
        bbox = draw.textbbox((0, 0), en_text, font=font)
        text_w = bbox[2] - bbox[0]
    while text_w > int(W * 0.80) and size > 80:
        size -= 5
        font = load_font(size)
        bbox = draw.textbbox((0, 0), en_text, font=font)
        text_w = bbox[2] - bbox[0]

    text_h = bbox[3] - bbox[1]
    main_x = 60
    main_y = int(H * 0.75) - text_h // 2

    for ox, oy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4), (4, 0), (-4, 0), (0, -4)]:
        draw.text((main_x + ox, main_y + oy), en_text, font=font, fill=(0, 0, 0, 200))
    draw.text((main_x, main_y), en_text, font=font, fill=(255, 255, 255, 255))

    tag_font = load_font(36)
    tag_text = "[Playlist]"
    for ox, oy in [(2, 2), (-2, 2), (2, -2)]:
        draw.text((40 + ox, 30 + oy), tag_text, font=tag_font, fill=(0, 0, 0, 180))
    draw.text((40, 30), tag_text, font=tag_font, fill=(255, 255, 255, 255))

    wm_font = load_font(28)
    wm_text = "J_Jlaylist"
    wm_bbox = draw.textbbox((0, 0), wm_text, font=wm_font)
    wm_w = wm_bbox[2] - wm_bbox[0]
    wm_h = wm_bbox[3] - wm_bbox[1]
    wm_x = W - wm_w - 40
    wm_y = H - wm_h - 30
    for ox, oy in [(2, 2), (-2, 2), (2, -2)]:
        draw.text((wm_x + ox, wm_y + oy), wm_text, font=wm_font, fill=(0, 0, 0, 180))
    draw.text((wm_x, wm_y), wm_text, font=wm_font, fill=(220, 220, 220, 255))

    return canvas.convert("RGB")


def make_thumbnail(video_id, title):
    mood = classify_mood(title)
    seed = abs(hash(video_id)) % 100000
    bg_path = pick_background(mood, seed)
    if not bg_path:
        raise RuntimeError(f"배경 없음: mood={mood}")
    canvas = prepare_bg(bg_path, seed)
    en_text = pick_en_text(title, mood, seed)
    final = render_thumbnail(canvas, en_text)
    out_path = OUT_DIR / f"{video_id}.jpg"
    final.save(out_path, "JPEG", quality=90, optimize=True)
    return out_path, mood, en_text


# ── 백업 / 업로드 / 로그 ─────────────────────────────────────────────────
def backup_existing_thumbnail(yt, video_id):
    backup_log = BACKUP_DIR / "v51_thumbnail_urls.json"
    existing = {}
    if backup_log.exists():
        existing = json.loads(backup_log.read_text(encoding="utf-8"))
    if video_id in existing:
        return
    try:
        resp = yt.videos().list(part="snippet", id=video_id).execute()
        thumbs = resp["items"][0]["snippet"].get("thumbnails", {})
        url = (thumbs.get("maxres") or thumbs.get("standard")
               or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
        existing[video_id] = {"url": url, "backed_up_at": datetime.now().isoformat()}
        backup_log.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def upload_thumbnail(yt, video_id, jpg_path):
    media = MediaFileUpload(str(jpg_path), mimetype="image/jpeg")
    yt.thumbnails().set(videoId=video_id, media_body=media).execute()


def load_json(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


# ── main ─────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--daily-limit", type=int, default=0,
                    help="하루 최대 N개 적용 (자동화 권장: 6)")
    ap.add_argument("--longform-only", action="store_true")
    ap.add_argument("--shorts-only", action="store_true")
    ap.add_argument("--since", type=str, default="")
    ap.add_argument("--video-id", type=str, default="")
    ap.add_argument("--auto", action="store_true",
                    help="자동화 모드: 종료 코드 + ::RESULT:: 출력")
    ap.add_argument("--reset-progress", action="store_true")
    args = ap.parse_args()

    if not (args.check or args.preview or args.apply):
        ap.print_help()
        sys.exit(0)

    if args.reset_progress:
        if PROGRESS_FILE.exists():
            PROGRESS_FILE.unlink()
        print("⚠️ progress.json 초기화 완료")

    if not BG_DIR.exists():
        sys.exit(f"❌ 배경 폴더 없음: {BG_DIR}")

    yt = get_youtube()
    print("[YouTube] 영상 목록 조회 중...")
    all_videos = get_all_videos(yt)
    print(f"  → 전체 {len(all_videos)}개\n")

    videos = all_videos[:]
    if args.video_id:
        videos = [v for v in videos if v["id"] == args.video_id]
    if args.longform_only:
        videos = [v for v in videos if not v["is_shorts"]]
    if args.shorts_only:
        videos = [v for v in videos if v["is_shorts"]]
    if args.since:
        videos = [v for v in videos if v.get("published_at", "")[:10] >= args.since]

    progress = load_json(PROGRESS_FILE)
    applied_ids = set(progress.get("applied", []))
    if args.apply:
        videos = [v for v in videos if v["id"] not in applied_ids]
        print(f"[Progress] 이미 적용 {len(applied_ids)}개 제외 → 미적용 {len(videos)}개\n")

    if args.daily_limit > 0:
        videos = videos[:args.daily_limit]
    elif args.limit > 0:
        videos = videos[:args.limit]

    if args.check:
        print(f"[CHECK] 처리 대상 {len(videos)}개")
        for v in videos:
            kind = "Shorts" if v["is_shorts"] else "롱폼  "
            mood = classify_mood(v["title"])
            print(f"  {kind} | {mood:<16} | {v['id']} | {v['title'][:50]}")
        return

    log = load_json(LOG_FILE)
    success, fail, rate_limit_hit = 0, 0, False
    print(f"[{'APPLY' if args.apply else 'PREVIEW'}] 시작 — {len(videos)}개")
    if args.apply:
        print(f"  daily-limit: {args.daily_limit or 'OFF'}, 누적 적용: {len(applied_ids)}개\n")

    applied_today = []

    for i, v in enumerate(videos, 1):
        vid = v["id"]
        title = v["title"]
        try:
            out_path, mood, en_text = make_thumbnail(vid, title)
            print(f"[{i}/{len(videos)}] ✓ 생성 | {mood:<16} | {en_text:<26} | {vid}")
            if args.apply:
                backup_existing_thumbnail(yt, vid)
                upload_thumbnail(yt, vid, out_path)
                print(f"              ↑ 업로드 완료")
                applied_ids.add(vid)
                applied_today.append({"id": vid, "title": title, "en_text": en_text, "mood": mood})
                progress["applied"] = sorted(applied_ids)
                progress["last_run"] = datetime.now(timezone.utc).isoformat()
                save_json(PROGRESS_FILE, progress)
                log[vid] = {
                    "applied_at": datetime.now().isoformat(),
                    "mood": mood,
                    "en_text": en_text,
                    "title": title,
                }
                save_json(LOG_FILE, log)
                time.sleep(2.0)
            success += 1
        except HttpError as e:
            err_str = str(e)
            if "uploadRateLimitExceeded" in err_str or "429" in err_str:
                print(f"[{i}/{len(videos)}] 🛑 RATE LIMIT 도달. 즉시 중단.")
                rate_limit_hit = True
                fail += 1
                break
            print(f"[{i}/{len(videos)}] ✗ API 실패 | {vid} | {e}")
            fail += 1
        except Exception as e:
            print(f"[{i}/{len(videos)}] ✗ 실패 | {vid} | {e}")
            fail += 1

    # 보고
    print(f"\n── 완료 ──")
    print(f"  성공: {success}")
    print(f"  실패: {fail}")
    if args.apply:
        total_progress = len(applied_ids)
        remaining_count = len([v for v in all_videos if v["id"] not in applied_ids])
        print(f"  누적 적용: {total_progress}개 / 전체 {len(all_videos)}개")
        print(f"  남은 영상: {remaining_count}개")
        eta_days = max(1, (remaining_count + 5) // 6) if remaining_count > 0 else 0
        print(f"  예상 완료: D+{eta_days}일")

    if args.auto:
        # 자동화 알림용 구조화 출력 (이메일이 파싱)
        print("\n::REPORT_START::")
        print(json.dumps({
            "date": datetime.now(timezone.utc).isoformat(),
            "success": success,
            "fail": fail,
            "rate_limit_hit": rate_limit_hit,
            "applied_today": applied_today,
            "total_applied": len(applied_ids),
            "total_videos": len(all_videos),
            "remaining": len([v for v in all_videos if v["id"] not in applied_ids]),
        }, ensure_ascii=False, indent=2))
        print("::REPORT_END::")

        if rate_limit_hit:
            print("::RESULT::RATE_LIMIT")
            sys.exit(2)
        if fail > 0 and success == 0:
            print("::RESULT::FAIL")
            sys.exit(1)
        print(f"::RESULT::SUCCESS::{success}")
        sys.exit(0)


if __name__ == "__main__":
    main()