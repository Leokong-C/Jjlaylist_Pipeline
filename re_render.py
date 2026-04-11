"""
re_render.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
기존 output/ 폴더의 MP4 파일을 새 generator.py 설정으로 재렌더링

변경사항:
  - 영상 페이드인 0.8초 / 오디오 페이드인 1.5초 추가
  - 영상 페이드아웃 3초 / 오디오 페이드아웃 4초 추가
  - 비디오 비트레이트 500k → 800k
  - 오디오 비트레이트 128k → 192k
  - -movflags +faststart (웹 스트리밍 최적화)

사용법:
  python re_render.py --preview   # 매칭 결과만 확인 (렌더링 안 함)
  python re_render.py             # 전체 재렌더링
  python re_render.py --limit 3   # 3개만 테스트
"""

import subprocess, os, re, argparse
from pathlib import Path

# ── 경로 설정 ─────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
MUSIC_DIR   = BASE_DIR / "music"
OUTPUT_DIR  = BASE_DIR / "output"
THUMB_DIR   = BASE_DIR / "assets" / "thumbnails"
SKIP_FILES  = {"mixed_playlist"}   # 재렌더링 제외 파일명 (확장자 제외)

# ── 페이드 설정 ───────────────────────────────────────────────────────────
FADE_IN_VIDEO  = 0.8
FADE_IN_AUDIO  = 1.5
FADE_OUT_VIDEO = 3.0
FADE_OUT_AUDIO = 4.0
DURATION_SEC   = 3600   # 1시간


def normalize(name: str) -> str:
    """파일명 정규화: 번호 접두사 제거, 소문자, 공백 압축"""
    # "1. ", "10. ", "4 ." 같은 번호 접두사 제거
    name = re.sub(r"^\d+\s*\.\s*", "", name)
    name = name.lower().strip()
    name = re.sub(r"\s+", " ", name)
    return name


def find_matching_mp3(mp4_stem: str, music_files: list[Path]) -> Path | None:
    """MP4 파일명에 맞는 MP3 찾기 — 3단계 전략"""
    # 전략 1: 완전 일치
    exact = MUSIC_DIR / (mp4_stem + ".mp3")
    if exact.exists():
        return exact

    # 전략 2: 정규화 후 일치
    target = normalize(mp4_stem)
    for mp3 in music_files:
        if normalize(mp3.stem) == target:
            return mp3

    # 전략 3: 부분 일치 (목표가 mp3 stem에 포함되거나 반대)
    for mp3 in music_files:
        norm_mp3 = normalize(mp3.stem)
        if target in norm_mp3 or norm_mp3 in target:
            return mp3

    return None


def get_thumbnail(index: int) -> Path | None:
    """썸네일 순환 선택"""
    thumbs = sorted([
        f for f in THUMB_DIR.rglob("*.png")
        if "auto" not in str(f).lower()
    ])
    if not thumbs:
        thumbs = sorted(THUMB_DIR.rglob("*.png"))
    if not thumbs:
        return None
    return thumbs[index % len(thumbs)]


def render_video(mp3_path: Path, thumb_path: Path, output_path: Path) -> bool:
    """FFmpeg 렌더링 (페이드인/아웃 적용)"""
    fo_v = DURATION_SEC - FADE_OUT_VIDEO
    fo_a = DURATION_SEC - FADE_OUT_AUDIO

    vf = (
        f"scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"fade=t=in:st=0:d={FADE_IN_VIDEO},"
        f"fade=t=out:st={fo_v:.1f}:d={FADE_OUT_VIDEO}"
    )
    af = (
        f"afade=t=in:st=0:d={FADE_IN_AUDIO},"
        f"afade=t=out:st={fo_a:.1f}:d={FADE_OUT_AUDIO}"
    )

    cmd = [
        "ffmpeg",
        "-loop", "1",
        "-i", str(thumb_path),
        "-stream_loop", "-1",
        "-i", str(mp3_path),
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-preset", "fast",
        "-c:a", "aac",
        "-b:v", "800k",
        "-b:a", "192k",
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-af", af,
        "-t", str(DURATION_SEC),
        "-shortest",
        "-movflags", "+faststart",
        "-y",
        str(output_path)
    ]

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="ignore"
    )
    return result.returncode == 0


def main():
    parser = argparse.ArgumentParser(description="J_Jlaylist 재렌더링")
    parser.add_argument("--preview", action="store_true", help="매칭 확인만 (렌더링 안 함)")
    parser.add_argument("--limit",   type=int, default=None, help="처리 개수 제한")
    args = parser.parse_args()

    # MP4 목록
    mp4_files = sorted([
        f for f in OUTPUT_DIR.glob("*.mp4")
        if f.stem not in SKIP_FILES
    ])

    # MP3 전체 목록
    music_files = list(MUSIC_DIR.glob("*.mp3"))

    print(f"\n📁 output/ MP4: {len(mp4_files)}개")
    print(f"🎵 music/ MP3: {len(music_files)}개")
    print(f"🖼️  thumbnails: {len(list(THUMB_DIR.rglob('*.png')))}개")
    print("-" * 65)

    matched   = []
    unmatched = []

    for mp4 in mp4_files:
        mp3 = find_matching_mp3(mp4.stem, music_files)
        if mp3:
            matched.append((mp4, mp3))
        else:
            unmatched.append(mp4)

    print(f"\n✅ 매칭 성공: {len(matched)}개")
    print(f"❌ 매칭 실패: {len(unmatched)}개")

    if unmatched:
        print("\n매칭 실패 목록:")
        for f in unmatched:
            print(f"  - {f.name}")

    if args.preview:
        print("\n[미리보기 모드 — 매칭 결과]")
        for mp4, mp3 in matched[:20]:
            print(f"  {mp4.name[:40]:40s} ← {mp3.name[:35]}")
        if len(matched) > 20:
            print(f"  ... 외 {len(matched)-20}개")
        print(f"\n실제 렌더링: python re_render.py")
        return

    # 렌더링
    target = matched[:args.limit] if args.limit else matched
    print(f"\n🚀 재렌더링 시작 ({len(target)}개) — 약 {len(target)*12}분 예상")
    print("=" * 65)

    ok = fail = 0
    for i, (mp4, mp3) in enumerate(target):
        thumb = get_thumbnail(i)
        print(f"\n[{i+1:2d}/{len(target)}] {mp4.name[:50]}")
        print(f"         MP3: {mp3.name[:45]}")
        print(f"         IMG: {thumb.name if thumb else '없음'}")

        if not thumb:
            print("         ❌ 썸네일 없음 — 건너뜀")
            fail += 1
            continue

        success = render_video(mp3, thumb, mp4)   # 같은 경로에 덮어쓰기
        if success:
            size = mp4.stat().st_size / (1024*1024)
            print(f"         ✅ 완료 ({size:.1f}MB)")
            ok += 1
        else:
            print(f"         ❌ 렌더링 실패")
            fail += 1

    print(f"\n결과: ✅ {ok}개 / ❌ {fail}개")
    if unmatched:
        print(f"⚠️  MP3 매칭 실패 {len(unmatched)}개는 재렌더링되지 않았습니다.")
        print("   music/ 폴더에서 파일명 확인 후 수동 처리 필요")


if __name__ == "__main__":
    main()