"""
shorts_generator.py
--------------------
믹스 MP4 → 수직 9:16 (1080x1920) 58초 YouTube Shorts 클립 자동 생성

사용법:
    python shorts_generator.py               # output/mixes/ 전체 처리
    python shorts_generator.py --batch 3     # batch_log의 배치 3번만 처리
    python shorts_generator.py --file path   # 단일 파일 처리

출력: output/shorts/  (reels_exporter.py가 이 폴더를 참조함)
"""

import subprocess
import json
import argparse
import sys
import os
import glob
from pathlib import Path
from datetime import datetime

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
MIXES_DIR   = BASE_DIR / "output" / "mixes"
SHORTS_DIR  = BASE_DIR / "output" / "shorts"
BATCH_LOG   = BASE_DIR / "batch_log.json"

# ── Shorts 스펙 ────────────────────────────────────────────────────────────────
SHORTS_W        = 1080
SHORTS_H        = 1920
SHORTS_DURATION = 58        # YouTube Shorts 최대 60초, 여유 2초
START_OFFSET    = 30        # 믹스 시작 후 30초 지점부터 (인트로 스킵)
FADE_DURATION   = 1.0       # 페이드인/아웃 (초)

# ── 로드: batch_log.json ───────────────────────────────────────────────────────
def load_batch_log() -> dict:
    if not BATCH_LOG.exists():
        return {}
    with open(BATCH_LOG, "r", encoding="utf-8") as f:
        return json.load(f)

# ── 믹스 파일 탐색 ──────────────────────────────────────────────────────────────
def find_mix_files(batch_num: int | None = None) -> list[Path]:
    all_files = sorted(MIXES_DIR.glob("*.mp4"))

    if not all_files:
        return []

    # batch_num 미지정 → 전체 반환
    if batch_num is None:
        return all_files

    # 1순위: batch_log에서 mix_title 매칭
    log = load_batch_log()
    key = str(batch_num)
    if key in log:
        mix_title = log[key].get("mix_title", "")
        matched = [f for f in all_files if mix_title and mix_title[:15] in f.name]
        if matched:
            return matched

    # 2순위: #03, #3, 03 숫자 패턴 매칭
    patterns = [
        f"#{batch_num:02d} ",   # #03 (공백 포함)
        f"#{batch_num:02d}.",   # #03. (점 포함)
        f"#{batch_num:02d}_",   # #03_
        f"MIX #{batch_num:02d}",  # MIX #03
    ]
    matched = [
        f for f in all_files
        if any(p in f.name for p in patterns)
    ]
    if matched:
        return matched

    # 3순위: 인덱스 순서 (배치 번호 = 파일 순서)
    idx = batch_num - 1
    if 0 <= idx < len(all_files):
        print(f"  [INFO] 파일명 패턴 매칭 실패 → {batch_num}번째 파일로 처리")
        return [all_files[idx]]

    return []

    # 전체 처리
    files = sorted(MIXES_DIR.glob("*.mp4"))
    return files

# ── 이미 생성된 Shorts 확인 ────────────────────────────────────────────────────
def already_generated(mix_path: Path) -> bool:
    stem = mix_path.stem
    out_path = SHORTS_DIR / f"{stem}_shorts.mp4"
    return out_path.exists()

# ── FFmpeg: 세로 변환 ──────────────────────────────────────────────────────────
def make_shorts_clip(mix_path: Path, force: bool = False, thumb_path: Path = None) -> Path | None:
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem     = mix_path.stem
    out_path = SHORTS_DIR / f"{stem}_shorts.mp4"

    if out_path.exists() and not force:
        print(f"  [SKIP] 이미 존재: {out_path.name}")
        return out_path

    print(f"  [변환] {mix_path.name}  →  {out_path.name}")

    try:
        probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
                     "-show_streams", str(mix_path)]
        probe_result = subprocess.run(probe_cmd, capture_output=True,
                                      encoding="utf-8", errors="ignore")
        probe_data = json.loads(probe_result.stdout)
        video_stream = next(
            (s for s in probe_data.get("streams", []) if s["codec_type"] == "video"), None)
        src_w = int(video_stream.get("width", 1920)) if video_stream else 1920
        src_h = int(video_stream.get("height", 1080)) if video_stream else 1080
    except Exception:
        src_w, src_h = 1920, 1080

    fg_h = min(SHORTS_H, int(SHORTS_W * src_h / src_w))
    fg_w = SHORTS_W
    fade_out_start = SHORTS_DURATION - FADE_DURATION

    # 썸네일 있으면 앞에 2초 붙이기
    if thumb_path and thumb_path.exists():
        temp_path = SHORTS_DIR / f"{stem}_shorts_temp.mp4"

        # Step 1: 메인 Shorts 클립 생성 (SHORTS_DURATION - 2초)
        main_duration = SHORTS_DURATION - 2
        fade_out_start_main = main_duration - FADE_DURATION
        text_start = main_duration - 3
        vf = (
            f"[0:v]split=2[bg_src][fg_src];"
            f"[bg_src]scale={SHORTS_W}:{SHORTS_H}:force_original_aspect_ratio=increase,"
            f"crop={SHORTS_W}:{SHORTS_H},boxblur=20:5[bg];"
            f"[fg_src]scale={fg_w}:{fg_h}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"drawtext=text='🎵 Full 1Hour Mix':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=h-220"
            f":enable='gte(t,{text_start})',"
            f"drawtext=text='Link in Comments':fontcolor=white:fontsize=40:x=(w-text_w)/2:y=h-155"
            f":enable='gte(t,{text_start})',"
            f"drawtext=text='J_Jlaylist':fontcolor=0xCCCCCC:fontsize=32:x=(w-text_w)/2:y=h-100"
            f":enable='gte(t,{text_start})'[vout]"
        )
        af = (f"afade=t=in:st=0:d={FADE_DURATION},"
              f"afade=t=out:st={fade_out_start_main}:d={FADE_DURATION}")

        cmd_main = [
            "ffmpeg", "-y", "-ss", str(START_OFFSET),
            "-i", str(mix_path), "-t", str(main_duration),
            "-filter_complex", vf,
            "-map", "[vout]", "-map", "0:a", "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-r", "30",
            "-s", f"{SHORTS_W}x{SHORTS_H}", "-movflags", "+faststart",
            str(temp_path)
        ]
        r = subprocess.run(cmd_main, capture_output=True, encoding="utf-8", errors="ignore")
        if r.returncode != 0:
            print(f"  [ERROR] 메인 클립 생성 실패:\n{r.stderr[-500:]}")
            return None

        # Step 2: 썸네일 → 2초 정지 클립 생성
        thumb_clip = SHORTS_DIR / f"{stem}_thumb_clip.mp4"
        cmd_thumb = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(thumb_path),
            "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
            "-t", "2",
            "-vf", f"scale={SHORTS_W}:{SHORTS_H}:force_original_aspect_ratio=decrease,"
                   f"pad={SHORTS_W}:{SHORTS_H}:(ow-iw)/2:(oh-ih)/2",
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-r", "30",
            "-movflags", "+faststart",
            str(thumb_clip)
        ]
        r = subprocess.run(cmd_thumb, capture_output=True, encoding="utf-8", errors="ignore")
        if r.returncode != 0:
            print(f"  [ERROR] 썸네일 클립 생성 실패:\n{r.stderr[-500:]}")
            return None

        # Step 3: 썸네일 클립 + 메인 클립 concat
        concat_list = SHORTS_DIR / f"{stem}_concat.txt"
        concat_list.write_text(
            f"file '{thumb_clip.name}'\nfile '{temp_path.name}'\n",
            encoding="utf-8"
        )
        cmd_concat = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy", "-movflags", "+faststart",
            str(out_path)
        ]
        r = subprocess.run(cmd_concat, capture_output=True, encoding="utf-8", errors="ignore")

        # 임시 파일 삭제
        for f in [temp_path, thumb_clip, concat_list]:
            if f.exists():
                f.unlink()

        if r.returncode != 0:
            print(f"  [ERROR] concat 실패:\n{r.stderr[-500:]}")
            return None

    else:
        # 썸네일 없으면 기존 방식
        vf = (
            f"[0:v]split=2[bg_src][fg_src];"
            f"[bg_src]scale={SHORTS_W}:{SHORTS_H}:force_original_aspect_ratio=increase,"
            f"crop={SHORTS_W}:{SHORTS_H},boxblur=20:5[bg];"
            f"[fg_src]scale={fg_w}:{fg_h}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
        )
        af = (f"afade=t=in:st=0:d={FADE_DURATION},"
              f"afade=t=out:st={fade_out_start}:d={FADE_DURATION}")
        cmd = [
            "ffmpeg", "-y", "-ss", str(START_OFFSET),
            "-i", str(mix_path), "-t", str(SHORTS_DURATION),
            "-filter_complex", vf,
            "-map", "[vout]", "-map", "0:a", "-af", af,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "192k", "-r", "30",
            "-s", f"{SHORTS_W}x{SHORTS_H}", "-movflags", "+faststart",
            str(out_path)
        ]
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="ignore")
        if r.returncode != 0:
            print(f"  [ERROR] FFmpeg 실패:\n{r.stderr[-800:]}")
            return None

    size_mb = out_path.stat().st_size / 1_048_576
    print(f"  [OK] {out_path.name}  ({size_mb:.1f} MB)")
    return out_path

# ── batch_log 업데이트 ─────────────────────────────────────────────────────────
def update_batch_log_shorts(batch_num: int, shorts_path: Path):
    if not BATCH_LOG.exists():
        return
    log = load_batch_log()
    key = str(batch_num)
    if key in log:
        log[key]["shorts_path"]      = str(shorts_path)
        log[key]["shorts_generated"] = datetime.now().isoformat()
        with open(BATCH_LOG, "w", encoding="utf-8") as f:
            json.dump(log, f, ensure_ascii=False, indent=2)
        print(f"  [LOG] batch_log.json 업데이트 완료 (배치 {batch_num})")

# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    global START_OFFSET
    parser = argparse.ArgumentParser(
        description="믹스 MP4 → YouTube Shorts 9:16 58초 클립 생성"
    )
    parser.add_argument("--batch", type=int, default=None,
                        help="처리할 배치 번호 (미지정 시 전체)")
    parser.add_argument("--file",  type=str, default=None,
                        help="단일 MP4 파일 경로")
    parser.add_argument("--force", action="store_true",
                        help="이미 생성된 파일도 덮어쓰기")
    parser.add_argument("--start", type=int, default=START_OFFSET,
                        help=f"믹스 시작 오프셋 초 (기본: {START_OFFSET})")
    args = parser.parse_args()

    START_OFFSET = args.start

    print("=" * 60)
    print("  shorts_generator.py  —  J_Jlaylist Shorts 클립 생성")
    print("=" * 60)

    SHORTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 단일 파일 모드 ────────────────────────────────────────────────────────
    if args.file:
        p = Path(args.file)
        if not p.exists():
            print(f"[ERROR] 파일 없음: {p}")
            sys.exit(1)
        result = make_shorts_clip(p, force=args.force)
        if result:
            print(f"\n✅ 완료: {result}")
        else:
            print("\n❌ 변환 실패")
        return

    # ── 배치 또는 전체 모드 ───────────────────────────────────────────────────
    mix_files = find_mix_files(args.batch)

    if not mix_files:
        print(f"[ERROR] 처리할 MP4가 없습니다. 경로 확인: {MIXES_DIR}")
        sys.exit(1)

    print(f"\n처리 대상: {len(mix_files)}개 믹스\n")

    success, fail, skipped = [], [], []
    for i, mix in enumerate(mix_files, 1):
        print(f"[{i}/{len(mix_files)}] {mix.name}")
        if already_generated(mix) and not args.force:
            skipped.append(mix)
            print(f"  [SKIP] Shorts 이미 존재 (--force로 덮어쓰기)")
            continue

        # 배치 번호로 썸네일 경로 연결
        thumb = None
        if args.batch is not None:
            thumb_candidate = BASE_DIR / "thumbnails" / "output_v3" / f"thumb_v3_batch{args.batch}.jpg"
            if thumb_candidate.exists():
                thumb = thumb_candidate
                print(f"  [THUMB] {thumb_candidate.name} 사용")

        out = make_shorts_clip(mix, force=args.force, thumb_path=thumb)
        if out:
            success.append(out)
            # batch_log 업데이트 (배치 번호 지정된 경우)
            if args.batch is not None:
                update_batch_log_shorts(args.batch, out)
        else:
            fail.append(mix)

    # ── 결과 요약 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  완료: {len(success)}개  /  실패: {len(fail)}개  /  스킵: {len(skipped)}개")
    print(f"  출력 폴더: {SHORTS_DIR}")
    if success:
        print("\n  생성된 파일:")
        for f in success:
            print(f"    • {f.name}")
    if fail:
        print("\n  실패한 파일:")
        for f in fail:
            print(f"    ✗ {f.name}")
    print("=" * 60)
    print("\n  다음 단계: python reels_exporter.py")

if __name__ == "__main__":
    main()