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
        f"#{batch_num:02d}",   # #03
        f"#{batch_num}",       # #3
        f" {batch_num:02d}",   # 공백+03
        f"_{batch_num:02d}",   # _03
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
def make_shorts_clip(mix_path: Path, force: bool = False) -> Path | None:
    """
    [변환 로직]
    1. START_OFFSET초 지점부터 SHORTS_DURATION초 추출
    2. 영상: 가로 → crop 정사각형 → pad 1080x1920 (위아래 블러 배경)
       - 블러 배경: 원본을 1080x1920으로 scale 후 boxblur
       - 원본: 세로 중앙 정렬 오버레이
    3. 오디오: 페이드인 1초 / 페이드아웃 1초
    4. faststart (웹 스트리밍 최적화)
    """
    SHORTS_DIR.mkdir(parents=True, exist_ok=True)
    stem     = mix_path.stem
    out_path = SHORTS_DIR / f"{stem}_shorts.mp4"

    if out_path.exists() and not force:
        print(f"  [SKIP] 이미 존재: {out_path.name}")
        return out_path

    print(f"  [변환] {mix_path.name}  →  {out_path.name}")

    # ── 원본 영상 정보 확인 ──────────────────────────────────────────────────
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        str(mix_path)
    ]
    try:
        probe_result = subprocess.run(
            probe_cmd, capture_output=True,
            encoding="utf-8", errors="ignore"
        )
        probe_data = json.loads(probe_result.stdout)
        video_stream = next(
            (s for s in probe_data.get("streams", []) if s["codec_type"] == "video"),
            None
        )
        if video_stream:
            src_w = int(video_stream.get("width", 1920))
            src_h = int(video_stream.get("height", 1080))
        else:
            src_w, src_h = 1920, 1080
    except Exception:
        src_w, src_h = 1920, 1080

    # ── FFmpeg 필터 그래프 ───────────────────────────────────────────────────
    # [0:v] 두 갈래:
    #   bg  : scale to 1080x1920 → boxblur (배경)
    #   fg  : scale to fit height=1080 (가로 유지) → 중앙 overlay
    fg_h = min(SHORTS_H, int(SHORTS_W * src_h / src_w))  # 원본 비율 유지, 너비 1080
    fg_w = SHORTS_W

    vf = (
        f"[0:v]split=2[bg_src][fg_src];"
        f"[bg_src]scale={SHORTS_W}:{SHORTS_H}:force_original_aspect_ratio=increase,"
        f"crop={SHORTS_W}:{SHORTS_H},boxblur=20:5[bg];"
        f"[fg_src]scale={fg_w}:{fg_h}[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2[vout]"
    )

    fade_out_start = SHORTS_DURATION - FADE_DURATION
    af = (
        f"afade=t=in:st=0:d={FADE_DURATION},"
        f"afade=t=out:st={fade_out_start}:d={FADE_DURATION}"
    )

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(START_OFFSET),           # 입력 seek (빠름)
        "-i", str(mix_path),
        "-t", str(SHORTS_DURATION),
        "-filter_complex", vf,
        "-map", "[vout]",
        "-map", "0:a",
        "-af", af,
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "23",
        "-c:a", "aac",
        "-b:a", "192k",
        "-r", "30",
        "-s", f"{SHORTS_W}x{SHORTS_H}",
        "-movflags", "+faststart",
        str(out_path)
    ]

    result = subprocess.run(
        cmd, capture_output=True,
        encoding="utf-8", errors="ignore"
    )

    if result.returncode != 0:
        print(f"  [ERROR] FFmpeg 실패:\n{result.stderr[-800:]}")
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
        out = make_shorts_clip(mix, force=args.force)
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