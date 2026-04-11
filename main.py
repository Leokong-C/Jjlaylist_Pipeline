"""
main.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
전체 파이프라인: 믹스 생성 → 메타데이터 → 썸네일 → YouTube 업로드

사용법:
  python main.py --mode mixer              # 믹스 생성만 (4가지 테마 각 1개)
  python main.py --mode upload             # output/mixes/ 업로드만
  python main.py --mode all               # 생성 + 업로드 (전체 파이프라인)
  python main.py --mode all --mood night  # 특정 테마 1개만
  python main.py --mode all --count 2     # 테마당 2개씩
"""

import os, json, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

from mixer import create_mix, MOOD_TITLES
from uploader import generate_mix_metadata, upload_video


# ── 경로 ─────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
MIXES_DIR  = BASE_DIR / "output" / "mixes"
LOG_FILE   = BASE_DIR / "mix_upload_log.json"

# ── 업로드 스케줄 설정 ────────────────────────────────────────────────────
UPLOAD_HOUR    = 9      # 한국 시간 오전 9시
DAYS_INTERVAL  = 2      # 2일 간격 (월·수·금)
KST            = timezone(timedelta(hours=9))


def load_log() -> list:
    if LOG_FILE.exists():
        with open(LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_log(log: list):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def next_publish_time(log: list) -> str:
    """로그 기반으로 다음 예약 시각 계산"""
    base = datetime.now(KST).replace(
        hour=UPLOAD_HOUR, minute=0, second=0, microsecond=0
    )
    if log:
        last = datetime.fromisoformat(log[-1]["publish_at"])
        base = max(base, last + timedelta(days=DAYS_INTERVAL))
    else:
        # 첫 업로드는 내일
        base = base + timedelta(days=1)
    return base.isoformat()


# ── 썸네일 생성 (thumbnail_auto.py 연동) ─────────────────────────────────
def make_thumbnail(video_id: str, title: str, mood: str) -> str | None:
    try:
        from thumbnail_auto import generate_thumbnail
        img = generate_thumbnail(video_id, title)
        return str(img)
    except Exception as e:
        print(f"  ⚠️  썸네일 생성 실패: {e}")
        return None


# ── 단일 믹스 전체 파이프라인 ─────────────────────────────────────────────
def run_mix_pipeline(mood: str, mix_index: int,
                     used_songs: set, do_upload: bool,
                     publish_at: str = None) -> dict:
    """믹스 생성 → 메타데이터 → 썸네일 → 업로드"""

    # 1. 믹스 생성
    mix = create_mix(mood=mood, mix_index=mix_index, used_songs=used_songs)

    # 2. 메타데이터 생성 (Claude API)
    print("\n🤖 메타데이터 생성 중...")
    meta = generate_mix_metadata(mix)
    title = meta.get("title_ko") or meta.get("title", "")
    print(f"  제목: {title}")

    result = {
        "mix":      mix,
        "metadata": meta,
        "video_id": None,
        "publish_at": publish_at,
    }

    if not do_upload:
        return result

    # 3. 업로드
    print(f"\n🚀 업로드 시작...")
    video_id = upload_video(
        video_path=mix["output"],
        metadata=meta,
        thumbnail_path=mix.get("thumbnail"),
        publish_at=publish_at,
    )
    result["video_id"] = video_id

    # 4. 썸네일 교체 (thumbnail_auto.py 버전으로)
    thumb_path = make_thumbnail(video_id, title, mood)
    if thumb_path:
        try:
            from uploader import get_youtube_client
            from googleapiclient.http import MediaFileUpload
            yt = get_youtube_client()
            yt.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumb_path, mimetype="image/jpeg")
            ).execute()
            print("  🖼  SEO 썸네일 교체 완료")
        except Exception as e:
            print(f"  ⚠️  썸네일 교체 실패: {e}")

    return result


# ── 모드별 실행 ───────────────────────────────────────────────────────────
def run_mixer_only(moods: list, count: int):
    """믹스 생성만"""
    used, idx = set(), 1
    for mood in moods:
        for _ in range(count):
            try:
                create_mix(mood=mood, mix_index=idx, used_songs=used)
                idx += 1
            except Exception as e:
                print(f"❌ 믹스 #{idx} 실패: {e}")
    print(f"\n✅ 생성 완료 → {MIXES_DIR}")


def run_upload_only():
    """output/mixes/ 에 있는 MP4 업로드 (메타데이터 없을 때 기본값 사용)"""
    mp4s = sorted(MIXES_DIR.glob("*.mp4"))
    log  = load_log()
    uploaded_ids = {l.get("output") for l in log}

    targets = [f for f in mp4s if str(f) not in uploaded_ids]
    print(f"업로드 대상: {len(targets)}개 (전체 {len(mp4s)}개)")

    for mp4 in targets:
        publish_at = next_publish_time(log)
        # 파일명에서 기본 메타데이터
        stem  = mp4.stem
        meta  = {
            "title_ko":    f"[Playlist] 🎧 {stem} | #Citypop",
            "description": f"Japanese City Pop Mix\n\n#citypop #시티팝 #lofi",
            "tags":        ["citypop", "시티팝", "lofi", "japanese city pop", "j_jlaylist"],
        }
        try:
            vid_id = upload_video(str(mp4), meta, publish_at=publish_at)
            entry  = {"output": str(mp4), "video_id": vid_id,
                      "publish_at": publish_at, "title": stem}
            log.append(entry)
            save_log(log)
        except Exception as e:
            print(f"❌ 업로드 실패: {mp4.name} → {e}")


def run_full_pipeline(moods: list, count: int):
    """생성 + 메타데이터 + 썸네일 + 업로드 전체"""
    log  = load_log()
    used = set()
    idx  = (log[-1].get("mix_index", 0) + 1) if log else 1

    for mood in moods:
        for _ in range(count):
            publish_at = next_publish_time(log)
            print(f"\n📅 예약 시각: {publish_at}")
            try:
                result = run_mix_pipeline(
                    mood=mood, mix_index=idx,
                    used_songs=used, do_upload=True,
                    publish_at=publish_at,
                )
                entry = {
                    "mix_index":  idx,
                    "mood":       mood,
                    "output":     result["mix"]["output"],
                    "video_id":   result["video_id"],
                    "publish_at": publish_at,
                    "title":      (result["metadata"].get("title_ko")
                                   or result["metadata"].get("title", "")),
                }
                log.append(entry)
                save_log(log)
                idx += 1
            except Exception as e:
                print(f"❌ 실패: {e}")
                idx += 1

    print(f"\n✅ 파이프라인 완료 — 로그: {LOG_FILE}")


# ── 진입점 ───────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="J_Jlaylist 파이프라인")
    p.add_argument("--mode",  default="all",
                   choices=["mixer", "upload", "all"],
                   help="mixer=생성만 / upload=업로드만 / all=전체")
    p.add_argument("--mood",  default="all",
                   choices=["night", "cafe", "melancholy", "dawn", "all"],
                   help="테마 (all=4테마 순환)")
    p.add_argument("--count", type=int, default=1,
                   help="테마당 생성 수 (기본 1)")
    args = p.parse_args()

    # 테마 목록 결정
    if args.mood == "all":
        moods = ["night", "cafe", "melancholy", "dawn"]
    else:
        moods = [args.mood]

    print(f"\n🎵 J_Jlaylist Pipeline | mode={args.mode} | mood={args.mood} | count={args.count}")
    print("=" * 60)

    if args.mode == "mixer":
        run_mixer_only(moods, args.count)
    elif args.mode == "upload":
        run_upload_only()
    elif args.mode == "all":
        run_full_pipeline(moods, args.count)


# ── 하위 호환: 기존 run_bulk_upload ──────────────────────────────────────
def run_bulk_upload(start_hour: int = 9):
    """기존 단일곡 일괄 업로드 (레거시)"""
    import json as _json
    from uploader import upload_video as _upload

    with open("metadata_output.json", "r", encoding="utf-8") as f:
        metadata_list = _json.load(f)

    output_files = sorted(Path("output/").glob("*.mp4"))
    thumbnails   = (list(Path("assets/thumbnails/").glob("*.jpg")) +
                    list(Path("assets/thumbnails/").glob("*.png")))
    kst       = timezone(timedelta(hours=9))
    base_time = datetime.now(kst).replace(hour=start_hour, minute=0,
                                          second=0, microsecond=0)
    for i, video in enumerate(output_files):
        meta  = metadata_list[i % len(metadata_list)]
        thumb = str(thumbnails[i % len(thumbnails)]) if thumbnails else None
        days_map   = [0, 2, 4]
        week       = i // 3
        day_offset = days_map[i % 3]
        publish    = (base_time + timedelta(weeks=week, days=day_offset)).isoformat()
        try:
            _upload(str(video), meta, thumb, publish)
        except Exception as e:
            print(f"오류: {video.name} → {e}")


if __name__ == "__main__":
    main()