"""
batch_mix.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
music/ 폴더의 MP3를 10개씩 순차 믹싱
완료된 곡 → music/processed/ 자동 이동
중단 후 재실행 시 이어서 진행 (batch_log.json)

사용법:
  python batch_mix.py --preview      # 배치 계획 미리보기
  python batch_mix.py --no-upload    # 믹스만 생성 (업로드 안 함)
  python batch_mix.py --limit 1      # 1개 배치만 테스트
  python batch_mix.py                # 전체 실행
"""

import os, json, shutil, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

# ── 상단에서 모두 import ──────────────────────────────────────────────────
from mixer    import mix_audio_crossfade, render_video, format_timestamps, pick_thumbnail
from uploader import generate_mix_metadata, upload_video

# ── 경로 설정 ─────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
MUSIC_DIR     = BASE_DIR / "music"
PROCESSED_DIR = MUSIC_DIR / "processed"
MIXES_DIR     = BASE_DIR / "output" / "mixes"
TEMP_DIR      = BASE_DIR / "output" / "temp"
BATCH_LOG     = BASE_DIR / "batch_log.json"

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
MIXES_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── 설정 ─────────────────────────────────────────────────────────────────
SONGS_PER_BATCH = 10
UPLOAD_HOUR     = 9       # 한국 시간 공개 시각
DAYS_INTERVAL   = 2       # 업로드 간격 (일)
KST             = timezone(timedelta(hours=9))


# ── 로그 ─────────────────────────────────────────────────────────────────
def load_log() -> list:
    if BATCH_LOG.exists():
        with open(BATCH_LOG, encoding="utf-8") as f:
            data = json.load(f)
        # dict로 저장된 경우 list로 변환
        if isinstance(data, dict):
            return list(data.values())
        return data
    return []


def save_log(log: list):
    # 항상 list로 저장
    if isinstance(log, dict):
        log = list(log.values())
    with open(BATCH_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ── 대기 MP3 목록 ─────────────────────────────────────────────────────────
def get_pending_songs() -> list:
    """music/ 직속 MP3만 (processed/ 하위 제외)"""
    return sorted(MUSIC_DIR.glob("*.mp3"))


def build_batches(songs: list) -> list:
    return [songs[i:i + SONGS_PER_BATCH]
            for i in range(0, len(songs), SONGS_PER_BATCH)]


# ── 예약 시각 계산 ────────────────────────────────────────────────────────
def next_publish_time(log: list) -> str:
    now  = datetime.now(KST)
    base = now.replace(hour=UPLOAD_HOUR, minute=0, second=0, microsecond=0)

    log_list = list(log.values()) if isinstance(log, dict) else log
    if log_list and "publish_at" in log_list[-1]:
        last = datetime.fromisoformat(log_list[-1]["publish_at"])
        base = last + timedelta(days=DAYS_INTERVAL)
        if base <= now:
            base = now.replace(hour=UPLOAD_HOUR, minute=0,
                               second=0, microsecond=0) + timedelta(days=1)
    else:
        base = base + timedelta(days=1)

    return base.isoformat()


# ── 단일 배치 처리 ────────────────────────────────────────────────────────
def process_batch(songs: list, batch_num: int, total_batches: int,
                  do_upload: bool, publish_at: str) -> dict:

    print(f"\n{'='*60}")
    print(f"배치 {batch_num}/{total_batches} | {len(songs)}곡 | 예약: {publish_at[:16]}")
    print("=" * 60)
    for i, s in enumerate(songs, 1):
        print(f"  {i:2d}. {s.stem}")

    # 1. 오디오 믹싱
    temp_audio = TEMP_DIR / f"batch_{batch_num:02d}.m4a"
    timestamps, total_dur = mix_audio_crossfade(songs, temp_audio)

    # 2. 썸네일 (없으면 None → render_video에서 단색 폴백)
    thumb = pick_thumbnail("all", seed=batch_num * 37)
    print(f"  🖼  썸네일: {thumb.name if thumb else '없음 (단색 폴백)'}")

    # 3. MP4 렌더링
    out_name = f"JAPANESE CITY POP MIX #{batch_num:02d}.mp4"
    out_path = MIXES_DIR / out_name
    render_video(temp_audio, thumb, out_path, total_dur)
    temp_audio.unlink(missing_ok=True)

    ts_str = format_timestamps(timestamps)
    size   = out_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ 생성 완료: {out_name} ({size:.1f}MB, {total_dur/60:.1f}분)")
    print(f"\n{ts_str}")

    # 4. 메타데이터 생성 + 업로드
    video_id = None
    if do_upload:
        mix_result = {
            "mood":         "all",
            "mix_index":    batch_num,
            "label":        "JAPANESE CITY POP MIX",
            "emoji":        "🎧",
            "timestamps":   ts_str,
            "duration_min": total_dur / 60,
            "songs":        [s.name for s in songs],
            "thumbnail":    str(thumb) if thumb else None,
        }
        print("\n🤖 메타데이터 생성 중...")
        meta  = generate_mix_metadata(mix_result)
        title = meta.get("title_ko") or meta.get("title", "")
        print(f"  제목: {title}")

        print(f"\n🚀 YouTube 업로드 중...")
        video_id = upload_video(
            video_path=str(out_path),
            metadata=meta,
            thumbnail_path=str(thumb) if thumb else None,
            publish_at=publish_at,
        )

    # 5. 완료된 MP3 → processed/ 이동
    print(f"\n📁 {len(songs)}곡 → music/processed/ 이동 중...")
    for song in songs:
        dest = PROCESSED_DIR / song.name
        shutil.move(str(song), str(dest))
        print(f"  ✓ {song.name}")

    return {
        "batch":      batch_num,
        "output":     str(out_path),
        "video_id":   video_id,
        "publish_at": publish_at,
        "songs":      [s.name for s in songs],
    }


# ── 진입점 ───────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="J_Jlaylist 배치 믹스")
    p.add_argument("--preview",   action="store_true", help="계획 미리보기만")
    p.add_argument("--no-upload", action="store_true", help="믹스만 (업로드 안 함)")
    p.add_argument("--limit",     type=int, default=None, help="배치 수 제한")
    args = p.parse_args()

    songs   = get_pending_songs()
    batches = build_batches(songs)
    log     = load_log()

    print(f"\n🎵 J_Jlaylist 배치 믹스")
    print(f"   대기 MP3: {len(songs)}개")
    print(f"   배치 수:  {len(batches)}개 ({SONGS_PER_BATCH}곡씩)")
    if len(songs) % SONGS_PER_BATCH:
        r = len(songs) % SONGS_PER_BATCH
        print(f"   마지막 배치: {r}곡 (부분 배치)")
    print(f"   처리 완료: {len(log)}개")

    # ── 미리보기 ──────────────────────────────────────────────────────────
    if args.preview:
        print(f"\n{'─'*60}")
        preview_log = list(log)
        for i, batch in enumerate(batches, 1):
            t = next_publish_time(preview_log)
            print(f"\n배치 {i:2d}/{len(batches)}  |  예약: {t[:16]}  |  {len(batch)}곡")
            for j, s in enumerate(batch, 1):
                print(f"  {j:2d}. {s.stem}")
            preview_log.append({"publish_at": t})
        print(f"\n실행: python batch_mix.py")
        return

    if not batches:
        print("\n⚠️  처리할 MP3 없음. music/ 폴더 확인.")
        return

    # ── 시작 번호 결정 ────────────────────────────────────────────────────
    log_list = list(log.values()) if isinstance(log, dict) else log
    log_list = list(log.values()) if isinstance(log, dict) else log
    start_num = (max(e["batch"] for e in log_list) + 1) if log_list else 1
    target        = batches[:args.limit] if args.limit else batches
    total_batches = len(target)

    print(f"\n  시작 번호: #{start_num}")
    print(f"  업로드:    {'안 함' if args.no_upload else '예약 업로드 진행'}")

    if not args.no_upload:
        confirm = input(f"\n총 {total_batches}개 배치를 처리합니다. 계속? (yes): ").strip().lower()
        if confirm != "yes":
            print("취소")
            return

    # ── 배치 실행 ─────────────────────────────────────────────────────────
    for i, batch in enumerate(target):
        batch_num  = start_num + i
        publish_at = next_publish_time(log)

        try:
            result = process_batch(
                songs=batch,
                batch_num=batch_num,
                total_batches=total_batches,
                do_upload=not args.no_upload,
                publish_at=publish_at,
            )
            log.append(result)
            save_log(log)
            print(f"\n📋 배치 {batch_num} 로그 저장 완료")

        except Exception as e:
            print(f"\n❌ 배치 {batch_num} 실패: {e}")
            print("   재실행 시 이어서 진행됩니다.")
            break

    # ── 최종 요약 ─────────────────────────────────────────────────────────
    remaining = get_pending_songs()
    print(f"\n{'='*60}")
    print(f"✅ 처리 완료: {len(log)}개 배치")
    print(f"   output/mixes/: {len(list(MIXES_DIR.glob('*.mp4')))}개")
    print(f"   music/ 남은 곡: {len(remaining)}개")
    if remaining:
        print(f"\n   {len(remaining)}곡은 music/에 대기 중")
        print(f"   새 곡 추가 후: python batch_mix.py --limit 1")


if __name__ == "__main__":
    main()