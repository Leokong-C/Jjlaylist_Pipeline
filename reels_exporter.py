"""
reels_exporter.py
------------------
output/shorts/ 의 Shorts MP4 → Instagram Reels용 CSV 매니페스트 생성
Buffer / Meta Business Suite 일괄 예약 업로드에 사용

⚠️  반드시 shorts_generator.py 실행 후 실행할 것
    (output/shorts/ 폴더 의존)

사용법:
    python reels_exporter.py               # 전체 처리
    python reels_exporter.py --batch 3     # 배치 3번만
    python reels_exporter.py --platform buffer   # buffer / meta (기본: buffer)
    python reels_exporter.py --start-date 2025-08-01  # 예약 시작일

출력:
    output/reels_manifest_YYYYMMDD_HHMMSS.csv
"""

import csv
import json
import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta

import anthropic  # Claude API (캡션 생성)

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
SHORTS_DIR   = BASE_DIR / "output" / "shorts"
BATCH_LOG    = BASE_DIR / "batch_log.json"
REELS_DIR    = BASE_DIR / "output"          # CSV 저장 위치

# ── Reels 업로드 스케줄 설정 ───────────────────────────────────────────────────
POST_HOUR    = 18          # KST 18:00 업로드 (Reels 황금 시간대)
POST_MINUTE  = 0
INTERVAL_DAYS = 2          # 2일 간격 업로드

# ── 해시태그 ──────────────────────────────────────────────────────────────────
BASE_HASHTAGS = (
    "#citypop #lofi #japanese #lofihiphop #chillmusic "
    "#vaporwave #studymusic #relaxingmusic #jazzmusic "
    "#夜の音楽 #シティポップ #lofimusic #aesthetic #chill"
)

# ── Claude API ────────────────────────────────────────────────────────────────
def generate_reels_caption(filename: str, platform: str) -> str:
    """
    파일명 기반으로 Reels 캡션 생성 (Claude API)
    플랫폼별 톤 조정: buffer(영문 감성) / meta(한영 혼용)
    """
    client = anthropic.Anthropic()

    stem   = Path(filename).stem.replace("_shorts", "").replace("_", " ")
    prompt_map = {
        "buffer": (
            f"Write a short, aesthetic Instagram Reels caption (2-3 lines) for a Japanese city pop / lofi music mix. "
            f"Theme/mood from filename: '{stem}'. "
            f"Style: dreamy, nostalgic, minimal. No emojis in first line. "
            f"End with 2-3 relevant emojis on the last line only. "
            f"Output ONLY the caption text, no explanation."
        ),
        "meta": (
            f"Instagram Reels 캡션을 작성해주세요. 일본 시티팝/로파이 음악 믹스. "
            f"파일명 테마: '{stem}'. "
            f"형식: 감성적인 한국어 1-2줄 + 영어 1줄. 마지막 줄 이모지 2-3개. "
            f"캡션 텍스트만 출력하세요."
        )
    }

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt_map.get(platform, prompt_map["buffer"])}]
        )
        caption = response.content[0].text.strip()
        # 마크다운 펜스 제거
        caption = caption.replace("```", "").strip()
        return caption
    except Exception as e:
        print(f"  [WARN] Claude API 캡션 생성 실패: {e}")
        return f"✨ Japanese City Pop Lofi Mix | {stem} | Chill & Relax 🌙🎵"

# ── CSV 필드 정의 ─────────────────────────────────────────────────────────────
def get_csv_fields(platform: str) -> list[str]:
    if platform == "meta":
        return [
            "file_path",        # 절대경로 또는 상대경로
            "caption",
            "scheduled_time",   # ISO 8601 (UTC)
            "location",
            "share_to_feed",    # TRUE / FALSE
            "cover_timestamp",  # 썸네일 추출 시간 (초)
        ]
    else:  # buffer
        return [
            "media_path",
            "caption",
            "scheduled_at",     # YYYY-MM-DD HH:MM (KST)
            "profile",          # Buffer 프로파일 이름
            "share_to_feed",
        ]

# ── batch_log 로드 ─────────────────────────────────────────────────────────────
def load_batch_log() -> dict:
    if not BATCH_LOG.exists():
        return {}
    with open(BATCH_LOG, "r", encoding="utf-8") as f:
        return json.load(f)

# ── Shorts 파일 탐색 ──────────────────────────────────────────────────────────
def find_shorts_files(batch_num: int | None = None) -> list[Path]:
    if not SHORTS_DIR.exists():
        print(f"[ERROR] output/shorts/ 폴더 없음. 먼저 shorts_generator.py 실행하세요.")
        return []

    files = sorted(SHORTS_DIR.glob("*_shorts.mp4"))

    if batch_num is not None:
        log = load_batch_log()
        key = str(batch_num)
        if key in log:
            shorts_path = log[key].get("shorts_path")
            if shorts_path and Path(shorts_path).exists():
                return [Path(shorts_path)]
        # 폴백: 배치 번호로 탐색
        files = [f for f in files
                 if f"batch{batch_num:02d}" in f.name.lower()
                 or f"batch_{batch_num}" in f.name.lower()]

    return files

# ── 예약 시간 생성 ────────────────────────────────────────────────────────────
def generate_schedule(
    count: int,
    start_date: str | None,
    platform: str
) -> list[str]:
    """
    KST 기준 POST_HOUR시 INTERVAL_DAYS 간격 예약 시간 리스트 반환
    platform == 'meta' → UTC 변환 (KST - 9h)
    """
    if start_date:
        base = datetime.strptime(start_date, "%Y-%m-%d")
    else:
        base = datetime.now().replace(hour=POST_HOUR, minute=POST_MINUTE,
                                      second=0, microsecond=0)
        if base < datetime.now():
            base += timedelta(days=1)

    base = base.replace(hour=POST_HOUR, minute=POST_MINUTE, second=0, microsecond=0)
    schedule = []
    for i in range(count):
        dt = base + timedelta(days=i * INTERVAL_DAYS)
        if platform == "meta":
            dt = dt - timedelta(hours=9)   # KST → UTC
            schedule.append(dt.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
        else:
            schedule.append(dt.strftime("%Y-%m-%d %H:%M"))
    return schedule

# ── CSV 생성 ──────────────────────────────────────────────────────────────────
def export_csv(
    shorts_files: list[Path],
    platform: str,
    start_date: str | None,
    generate_captions: bool
) -> Path:
    timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path   = REELS_DIR / f"reels_manifest_{timestamp}.csv"
    fields     = get_csv_fields(platform)
    schedules  = generate_schedule(len(shorts_files), start_date, platform)

    print(f"\n[CSV 생성] 플랫폼: {platform.upper()} | 파일 수: {len(shorts_files)}")
    print(f"  출력: {out_path.name}\n")

    rows = []
    for i, sf in enumerate(shorts_files):
        print(f"  [{i+1}/{len(shorts_files)}] {sf.name}")

        if generate_captions:
            print(f"    → Claude API 캡션 생성 중...")
            caption = generate_reels_caption(sf.name, platform)
        else:
            stem    = sf.stem.replace("_shorts", "").replace("_", " ")
            caption = f"✨ {stem} | Japanese City Pop Lofi Mix | Chill & Relax 🌙🎵"

        caption_with_tags = f"{caption}\n\n{BASE_HASHTAGS}"

        if platform == "meta":
            row = {
                "file_path":       str(sf.resolve()),
                "caption":         caption_with_tags,
                "scheduled_time":  schedules[i],
                "location":        "",
                "share_to_feed":   "TRUE",
                "cover_timestamp": "5",
            }
        else:  # buffer
            row = {
                "media_path":  str(sf.resolve()),
                "caption":     caption_with_tags,
                "scheduled_at": schedules[i],
                "profile":      "J_Jlaylist",
                "share_to_feed": "true",
            }

        rows.append(row)
        print(f"    ✓ 예약: {schedules[i]}")

    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    return out_path

# ── batch_log 업데이트 ─────────────────────────────────────────────────────────
def update_batch_log_reels(batch_num: int, csv_path: Path):
    if not BATCH_LOG.exists():
        return
    log = load_batch_log()
    key = str(batch_num)
    if key in log:
        log[key]["reels_csv"]       = str(csv_path)
        log[key]["reels_exported"]  = datetime.now().isoformat()
        with open(BATCH_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(f"\n  [LOG] batch_log.json 업데이트 완료 (배치 {batch_num})")

# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Shorts MP4 → Buffer/Meta Reels CSV 매니페스트 생성"
    )
    parser.add_argument("--batch",       type=int,   default=None,
                        help="처리할 배치 번호")
    parser.add_argument("--platform",    type=str,   default="buffer",
                        choices=["buffer", "meta"],
                        help="CSV 포맷 선택 (기본: buffer)")
    parser.add_argument("--start-date",  type=str,   default=None,
                        help="예약 시작일 YYYY-MM-DD (기본: 내일)")
    parser.add_argument("--no-captions", action="store_true",
                        help="Claude API 캡션 생성 건너뜀 (기본 캡션 사용)")
    args = parser.parse_args()

    print("=" * 60)
    print("  reels_exporter.py  —  J_Jlaylist Reels 매니페스트 생성")
    print("=" * 60)

    REELS_DIR.mkdir(parents=True, exist_ok=True)

    shorts_files = find_shorts_files(args.batch)
    if not shorts_files:
        print("[ERROR] 처리할 Shorts MP4 없음.")
        print("        먼저: python shorts_generator.py")
        sys.exit(1)

    csv_path = export_csv(
        shorts_files  = shorts_files,
        platform      = args.platform,
        start_date    = args.start_date,
        generate_captions = not args.no_captions,
    )

    if args.batch is not None:
        update_batch_log_reels(args.batch, csv_path)

    # ── 결과 요약 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  ✅ CSV 생성 완료: {csv_path.name}")
    print(f"  총 {len(shorts_files)}개 Reels 예약 항목")
    print(f"\n  업로드 방법:")
    if args.platform == "buffer":
        print("   1. Buffer.com → Publishing → Queue → Import CSV")
        print("   2. 생성된 CSV 파일 업로드")
    else:
        print("   1. Meta Business Suite → Planner → 일정 게시물 → CSV 가져오기")
        print("   2. 생성된 CSV 파일 업로드")
    print(f"\n  다음 단계: python blog_generator.py")
    print("=" * 60)

if __name__ == "__main__":
    main()