"""
thumbnail_auto.py  ·  J_Jlaylist  v4 (Final)
────────────────────────────────────────────────────────────────
레퍼런스 분석 최종 반영:
  KYOTO 1980 / 80s City Pop Rain / NEON NOIRE / TOKYO FUNK 스타일

핵심 규칙:
  1. 배경 이미지 풀프레임 + 부분 다크 오버레이
  2. 영문 대문자 1~2줄 (한글 없음)
  3. 이미지 구도에 맞는 텍스트 위치 (이미지별 고정)
  4. 서브텍스트 없음 — 타이틀만
  5. [Playlist] 좌상단 소형 / J_Jlaylist 우하단 소형

배경 폴더 구조:
  thumbnails/backgrounds/
    night_drive/      ← 차량내부.png, 소녀폰.png
    midnight_drive/   ← 차량내부.png
    neon_city/        ← 소녀폰.png, 커플.png
    cafe_rain/        ← 소녀폰.png
    melancholy/       ← 우주인.png, 커플.png
    dawn_morning/     ← 우주인.png

사용법:
  python thumbnail_auto.py --check              # 배경 이미지 현황
  python thumbnail_auto.py --preview --limit 3  # 3개 생성 확인
  python thumbnail_auto.py --apply   --limit 3  # 3개 업로드 테스트
  python thumbnail_auto.py --apply              # 전체 65개
  python thumbnail_auto.py --single VIDEO_ID '제목'
"""

import os, json, time, argparse, pickle, random, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# ── 경로 ─────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
BG_DIR       = BASE_DIR / "thumbnails" / "backgrounds"
OUTPUT_DIR   = BASE_DIR / "thumbnails" / "output"
PREVIEW_FILE = BASE_DIR / "seo_preview.json"
SCOPES       = ["https://www.googleapis.com/auth/youtube"]

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
W, H = 1280, 720

# ── 폰트 (영문 Bold 우선) ────────────────────────────────────────────────
FONT_PATHS = [
    "C:/Windows/Fonts/ariblk.ttf",    # Arial Black ← 1순위 (KYOTO 1980 스타일)
    "C:/Windows/Fonts/arialbd.ttf",   # Arial Bold
    "C:/Windows/Fonts/impact.ttf",    # Impact
    "C:/Windows/Fonts/verdanab.ttf",  # Verdana Bold
    "C:/Windows/Fonts/malgunbd.ttf",  # 맑은고딕 Bold (폴백)
    "C:/Windows/Fonts/malgun.ttf",
]

def get_font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

# ── 분위기 키워드 ─────────────────────────────────────────────────────────
MOOD_KEYWORDS = {
    "night_drive":    ["밤", "네온", "night", "neon", "도시", "드라이브", "city"],
    "midnight_drive": ["택시", "고속", "심야", "midnight", "highway", "기차", "도로"],
    "neon_city":      ["도쿄", "Tokyo", "긴자", "Ginza", "urban", "신호", "반사"],
    "cafe_rain":      ["카페", "비", "창가", "rain", "cafe", "조용", "편의점", "아침"],
    "melancholy":     ["이별", "추억", "그리움", "혼자", "alone", "cassette", "shirt", "끝", "마지막", "종전"],
    "dawn_morning":   ["새벽", "dawn", "morning", "sunrise", "여명"],
}
DEFAULT_MOOD = "night_drive"

def classify_mood(title: str, force_mood: str = None) -> str:
    """force_mood 지정 시 키워드 분석 없이 해당 mood 사용"""
    if force_mood and force_mood in MOOD_KEYWORDS:
        return force_mood
    tl = title.lower()
    scores = {m: sum(1 for kw in kws if kw.lower() in tl)
              for m, kws in MOOD_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else DEFAULT_MOOD

# 배치 번호 기반 mood 순환 (배치마다 다른 배경/분위기 보장)
BATCH_MOOD_CYCLE = [
    "night_drive",    # #01 차량내부
    "cafe_rain",      # #02 소녀폰/커플
    "melancholy",     # #03 소녀폰/우주인
    "dawn_morning",   # #04 우주인/차량내부
    "neon_city",      # #05 소녀폰/차량내부
    "midnight_drive", # #06 차량내부
    "night_drive",    # #07
    "cafe_rain",      # #08
    "melancholy",     # #09
    "dawn_morning",   # #10
]

def mood_for_batch(batch_num: int) -> str:
    return BATCH_MOOD_CYCLE[(batch_num - 1) % len(BATCH_MOOD_CYCLE)]

# ── 이미지별 텍스트 위치 설정 ────────────────────────────────────────────
# 각 배경 이미지의 구도에 맞게 텍스트 위치를 고정
# position: "bottom_center" | "bottom_left" | "top_left" | "center_left"
IMAGE_LAYOUT = {
    # 차량 내부 이미지 → 하단 중앙 (대시보드 위 어두운 영역)
    "차량":        "bottom_center",
    "car":         "bottom_center",
    "drive":       "bottom_center",
    "interior":    "bottom_center",
    # 애니 소녀 폰 이미지 → 좌하단 (소녀가 우측)
    "소녀":        "bottom_left",
    "girl":        "bottom_left",
    "phone":       "bottom_left",
    "window":      "bottom_left",
    # 우주인 이미지 → 좌상단 (우주인이 중앙~우측)
    "우주":        "top_left",
    "astro":       "top_left",
    "alone":       "top_left",
    "flower":      "top_left",
    # 커플 이미지 → 좌하단 (풀밭 영역)
    "couple":      "bottom_left",
    "커플":        "bottom_left",
}

# 분위기별 기본 위치 (이미지 파일명으로 판단 안 될 때)
MOOD_DEFAULT_POSITION = {
    "night_drive":    "bottom_center",
    "midnight_drive": "bottom_center",
    "neon_city":      "bottom_left",
    "cafe_rain":      "bottom_left",
    "melancholy":     "top_left",
    "dawn_morning":   "top_left",
}

def get_text_position(bg_filename: str, mood: str) -> str:
    name_lower = bg_filename.lower()
    for keyword, pos in IMAGE_LAYOUT.items():
        if keyword in name_lower:
            return pos
    return MOOD_DEFAULT_POSITION.get(mood, "bottom_left")

# ── 분위기별 영문 텍스트 풀 ───────────────────────────────────────────────
# 레퍼런스 스타일: KYOTO 1980 / 80s CITY POP RAIN / TOKYO FUNK / NEON NOIRE
MOOD_TEXT_POOL = {
    # 두 줄 균형: 각 줄이 비슷한 길이가 되도록 조정
    "night_drive": [
        "CITY POP RAIN",        # 한 줄
        "TOKYO NIGHT\nDRIVE",
        "NEON RAIN\nCITY POP",
        "MIDNIGHT\nCITY POP",
        "CITY POP\nNIGHT",
    ],
    "midnight_drive": [
        "MIDNIGHT\nCITY POP",
        "TOKYO NIGHT\nDRIVE",
        "LATE NIGHT\nCITY POP",
        "NEON DRIVE\nCITY POP",
        "CITY POP\nDRIVE",
    ],
    "neon_city": [
        "TOKYO\nCITY POP",
        "JAPANESE\nCITY POP",
        "URBAN\nCITY POP",
        "NEON CITY\nCITY POP",
        "TOKYO NEON\nCITY POP",
    ],
    "cafe_rain": [
        "LOFI CITY POP",        # 한 줄
        "CITY POP RAIN",        # 한 줄
        "LATE NIGHT\nLOFI",
        "LOFI JAPAN",           # 한 줄
        "CITY POP\nNIGHT",
    ],
    "melancholy": [
        "JAPANESE\nCITY POP",
        "80s CITY POP",         # 한 줄
        "MEMORIES\nOF TOKYO",
        "LOFI CITY POP",        # 한 줄
        "CITY POP\nNOSTALGIA",
    ],
    "dawn_morning": [
        "MORNING\nCITY POP",
        "DAWN CITY POP",        # 한 줄
        "LOFI JAPAN",           # 한 줄
        "80s CITY POP",         # 한 줄
        "CITY POP\nDAWN",
    ],
}

def pick_text(mood: str, title: str, seed: int) -> str:
    rng  = random.Random(seed)
    pool = MOOD_TEXT_POOL.get(mood, MOOD_TEXT_POOL["night_drive"])

    # 제목에 80s/90s 연도 키워드 있으면 반영
    if re.search(r'80s?|80년대', title, re.IGNORECASE):
        pool = [t.replace("CITY POP", "80s\nCITY POP") if "80s" not in t else t for t in pool]
    if re.search(r'90s?|90년대', title, re.IGNORECASE):
        pool = [t.replace("CITY POP", "90s\nCITY POP") if "90s" not in t else t for t in pool]

    return rng.choice(pool)

# ── 배경 이미지 선택 ──────────────────────────────────────────────────────
def pick_background(mood: str, seed: int):
    rng  = random.Random(seed)
    exts = ["*.jpg", "*.jpeg", "*.png", "*.webp"]

    mood_dir = BG_DIR / mood
    if mood_dir.exists():
        imgs = [f for ext in exts for f in mood_dir.glob(ext)]
        if imgs:
            return rng.choice(imgs)

    all_imgs = [f for ext in exts for f in BG_DIR.rglob(ext)]
    return rng.choice(all_imgs) if all_imgs else None

# ── 배경 이미지 준비 ──────────────────────────────────────────────────────
def prepare_bg(bg_path: Path, mood: str) -> Image.Image:
    bg = Image.open(bg_path).convert("RGB")
    bw, bh = bg.size

    # 커버 크롭 (1280x720)
    tr = W / H
    br = bw / bh
    if br > tr:
        nw, nh = int(bh * tr), bh
    else:
        nw, nh = bw, int(bw / tr)

    # 구도별 크롭 기준
    # 상단 인물 → 위에서 크롭 (top_left 포지션용 이미지)
    # 하단 여백 → 아래 포함해서 크롭
    left = (bw - nw) // 2
    top  = 0 if mood in ("melancholy", "dawn_morning") else (bh - nh) // 3

    top  = max(0, min(top, bh - nh))
    left = max(0, min(left, bw - nw))

    bg = bg.crop((left, top, left + nw, top + nh)).resize((W, H), Image.LANCZOS)
    bg = ImageEnhance.Color(bg).enhance(1.15)
    bg = ImageEnhance.Contrast(bg).enhance(1.08)
    return bg

# ── 텍스트 위치 계산 ─────────────────────────────────────────────────────
def calc_text_xy(position: str, lines: list, line_h: int,
                 draw: ImageDraw, font: ImageFont) -> tuple:
    total_h = len(lines) * line_h
    widths  = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
    max_w = max(widths) if widths else 400

    margin = 56

    if position == "bottom_center":
        x = (W - max_w) // 2
        y = H - total_h - 110   # 여백 증가
    elif position == "bottom_left":
        x = margin
        y = H - total_h - 110   # 여백 증가
    elif position == "top_left":
        x = margin
        y = 108
    elif position == "center_left":
        x = margin
        y = (H - total_h) // 2
    else:
        x = margin
        y = H - total_h - 110

    return x, y

# ── 썸네일 생성 (최종 버전) ───────────────────────────────────────────────
def generate_thumbnail(video_id: str, title: str, force_mood: str = None) -> Path:
    mood    = classify_mood(title, force_mood=force_mood)
    seed    = abs(hash(video_id)) % 100000
    bg_path = pick_background(mood, seed)

    # 배경
    if bg_path and Path(bg_path).exists():
        canvas = prepare_bg(Path(bg_path), mood)
        layout = get_text_position(Path(bg_path).name, mood)
    else:
        canvas = Image.new("RGB", (W, H), (8, 8, 18))
        d = ImageDraw.Draw(canvas)
        for y in range(H):
            t = y / H
            d.line([(0, y), (W, y)],
                   fill=(int(8*(1-t)+20*t), int(10*(1-t)+5*t), int(35*(1-t)+50*t)))
        layout = MOOD_DEFAULT_POSITION.get(mood, "bottom_left")

    canvas = canvas.convert("RGBA")

    # ── 오버레이: 자연스러운 그라디언트 ──
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ol = ImageDraw.Draw(ov)

    if layout in ("bottom_center", "bottom_left"):
        # 하단 그라디언트 — 부드럽게 (직사각형 아님)
        for y in range(H):
            dist_from_bottom = H - y
            if dist_from_bottom < 380:
                # 하단 380px: 0 → 185 부드럽게
                t = dist_from_bottom / 380
                a = int(185 * (1 - t**1.4))
                ol.rectangle([0, y, W, y+1], fill=(0, 0, 0, a))
            elif dist_from_bottom < 480:
                # 380~480px: 미세한 전환
                t = (dist_from_bottom - 380) / 100
                a = int(30 * (1 - t))
                ol.rectangle([0, y, W, y+1], fill=(0, 0, 0, a))
    elif layout == "top_left":
        # 상단 그라디언트
        for y in range(350):
            t = y / 350
            a = int(180 * (1 - t**1.4))
            ol.rectangle([0, y, W, y+1], fill=(0, 0, 0, a))

    # 상단 얇게 (로고 가독성)
    for y in range(70):
        a = int(130 * (1 - y/70))
        ol.rectangle([0, y, W, y+1], fill=(0, 0, 0, a))

    # 전체 균일 25% (이미지 색감 최대 살리기)
    ov_full = Image.new("RGBA", (W, H), (0, 0, 0, 64))
    canvas  = Image.alpha_composite(canvas, ov_full)
    canvas  = Image.alpha_composite(canvas, ov)
    canvas  = canvas.convert("RGB")
    draw    = ImageDraw.Draw(canvas)

    # 폰트 — 크기 조정 (108 → 86: 텍스트 잘림 방지)
    font_main  = get_font(86)
    font_badge = get_font(20)
    font_wm    = get_font(23)

    # 메인 텍스트
    en_text = pick_text(mood, title, seed)
    lines   = en_text.strip().split("\n")
    line_h  = 96   # 86px 폰트에 맞게 축소

    x, y = calc_text_xy(layout, lines, line_h, draw, font_main)

    for i, line in enumerate(lines):
        tx = x
        ty = y + i * line_h

        # 그림자 (자연스럽게)
        for dx, dy in [(5,5),(3,3),(1,1)]:
            draw.text((tx+dx, ty+dy), line, font=font_main, fill=(0, 0, 0))
        # 메인 흰색
        draw.text((tx, ty), line, font=font_main, fill=(255, 255, 255))

    # [Playlist] 뱃지 — 좌상단
    draw.text((48, 36), "[Playlist]", font=font_badge, fill=(210, 210, 210))

    # J_Jlaylist 워터마크 — 우하단
    wm   = "J_Jlaylist"
    bbox = draw.textbbox((0, 0), wm, font=font_wm)
    ww   = bbox[2] - bbox[0]
    draw.text((W - ww - 38, H - 42), wm, font=font_wm, fill=(185, 185, 185))

    out = OUTPUT_DIR / f"{video_id}.jpg"
    canvas.save(out, "JPEG", quality=95)
    return out

# ── YouTube 인증 ──────────────────────────────────────────────────────────
def get_youtube_client():
    creds = None
    tp    = BASE_DIR / "token.pickle"
    sec   = os.getenv("YOUTUBE_CLIENT_SECRET_FILE",
                      str(BASE_DIR / "client_secret.json"))
    if tp.exists():
        with open(tp, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(sec, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(tp, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)

# ── 영상 목록 ────────────────────────────────────────────────────────────
def fetch_videos(youtube):
    print("📡 영상 목록 수집...")
    ch  = youtube.channels().list(part="contentDetails", mine=True).execute()
    uid = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    videos, nt = [], None
    while True:
        pl = youtube.playlistItems().list(
            part="snippet", playlistId=uid, maxResults=50, pageToken=nt
        ).execute()
        for item in pl["items"]:
            sn  = item["snippet"]
            vid = sn["resourceId"]["videoId"]
            videos.append({"video_id": vid, "title": sn["title"],
                           "url": f"https://youtu.be/{vid}"})
        nt = pl.get("nextPageToken")
        if not nt:
            break
        time.sleep(0.3)

    # SEO 수정된 제목 반영
    if PREVIEW_FILE.exists():
        with open(PREVIEW_FILE, encoding="utf-8") as f:
            nmap = {r["video_id"]: r["new_title"]
                    for r in json.load(f) if r.get("title_changed")}
        for v in videos:
            if v["video_id"] in nmap:
                v["title"] = nmap[v["video_id"]]
    print(f"✅ {len(videos)}개")
    return videos

# ── 업로드 ───────────────────────────────────────────────────────────────
def upload_thumbnail(youtube, video_id: str, img_path: Path) -> bool:
    try:
        media = MediaFileUpload(str(img_path), mimetype="image/jpeg")
        youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
        return True
    except Exception as e:
        err = str(e)
        if "uploadNotEnabled" in err:
            print("  ⚠️  채널 인증 필요: YouTube Studio → 설정 → 채널 → 기능 사용 자격")
        else:
            print(f"  ❌ {type(e).__name__}: {err[:80]}")
        return False

# ── 배경 현황 ─────────────────────────────────────────────────────────────
def check_backgrounds():
    print(f"\n📁 배경 이미지 현황 ({BG_DIR})")
    total = 0
    for mood in MOOD_KEYWORDS:
        d    = BG_DIR / mood
        exts = ["*.jpg", "*.jpeg", "*.png", "*.webp"]
        imgs = [f for ext in exts for f in (d.glob(ext) if d.exists() else [])]
        names = ", ".join(f.name[:20] for f in imgs[:2])
        print(f"  {mood:18s} {'✅ '+str(len(imgs))+'장  '+names if imgs else '⚠️  없음'}")
        total += len(imgs)
    print(f"\n  합계: {total}장" + (" ✅" if total else " — 이미지를 각 폴더에 넣어주세요"))
    return total > 0

# ── 일괄 처리 ────────────────────────────────────────────────────────────
def run_batch(youtube, videos, do_upload: bool, limit=None):
    check_backgrounds()
    target = videos[:limit] if limit else videos
    print(f"\n{'🖼️  생성+업로드' if do_upload else '🖼️  생성만'} ({len(target)}개)")
    print("-" * 65)
    gen_ok = up_ok = up_fail = 0

    for i, v in enumerate(target, 1):
        vid, title = v["video_id"], v["title"]
        mood = classify_mood(title)
        bg   = pick_background(mood, abs(hash(vid)) % 100000)
        bg_name = Path(bg).name if bg else "폴백"
        print(f"[{i:2d}/{len(target)}] [{mood:14s}|{bg_name[:14]:14s}] {title[:28]}...")
        try:
            img = generate_thumbnail(vid, title)
            gen_ok += 1
            print(f"         ✅ {img.name}")
        except Exception as e:
            print(f"         ❌ {e}")
            continue
        if do_upload:
            if upload_thumbnail(youtube, vid, img):
                up_ok += 1
                print("         ✅ 업로드")
            else:
                up_fail += 1
            time.sleep(1.0)

    print(f"\n생성: {gen_ok}개 → thumbnails/output/")
    if do_upload:
        print(f"업로드: ✅ {up_ok}개 / ❌ {up_fail}개")

# ── 단일 처리 (main.py 통합) ─────────────────────────────────────────────
def process_single(video_id: str, title: str, upload: bool = True) -> Path:
    img = generate_thumbnail(video_id, title)
    if upload:
        yt = get_youtube_client()
        upload_thumbnail(yt, video_id, img)
    return img

# ── 진입점 ───────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="J_Jlaylist 썸네일 자동화 v4")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--preview", action="store_true", help="생성만")
    g.add_argument("--apply",   action="store_true", help="생성 + 업로드")
    g.add_argument("--single",  nargs=2, metavar=("VIDEO_ID", "TITLE"))
    g.add_argument("--check",   action="store_true", help="배경 현황 확인")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()

    if args.check:
        check_backgrounds()
        return

    if args.single:
        vid, title = args.single
        img = generate_thumbnail(vid, title)
        print(f"✅ 생성: {img}")
        yt = get_youtube_client()
        ok = upload_thumbnail(yt, vid, img)
        print("✅ 업로드 완료" if ok else "❌ 업로드 실패")
        return

    youtube = get_youtube_client()
    videos  = fetch_videos(youtube)
    run_batch(youtube, videos, do_upload=args.apply, limit=args.limit)
    if args.preview:
        print(f"\nthumbnails/output/ 폴더 확인 후:")
        print(f"python thumbnail_auto.py --apply")

if __name__ == "__main__":
    main()