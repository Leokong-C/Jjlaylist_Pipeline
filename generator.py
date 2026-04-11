import subprocess
import os
from pathlib import Path

# ── 페이드 설정 ───────────────────────────────────────────────────────────
FADE_IN_VIDEO  = 0.8   # 영상 페이드인 (초) — 검정에서 이미지로
FADE_IN_AUDIO  = 1.5   # 오디오 페이드인 (초) — 무음에서 풀볼륨으로
FADE_OUT_VIDEO = 3.0   # 영상 페이드아웃 (초) — 영상 끝에서 검정으로
FADE_OUT_AUDIO = 4.0   # 오디오 페이드아웃 (초) — 영상 끝에서 무음으로


def create_lofi_video(audio_path, image_path, output_path, duration_hours=1.0):
    duration_seconds = int(duration_hours * 3600)

    # 페이드아웃 시작 시점
    fade_out_video_start = duration_seconds - FADE_OUT_VIDEO
    fade_out_audio_start = duration_seconds - FADE_OUT_AUDIO

    # 비디오 필터: 스케일 → 페이드인 → 페이드아웃
    vf = (
        f"scale=1920:1080:force_original_aspect_ratio=decrease,"
        f"pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        f"fade=t=in:st=0:d={FADE_IN_VIDEO},"
        f"fade=t=out:st={fade_out_video_start:.1f}:d={FADE_OUT_VIDEO}"
    )

    # 오디오 필터: 페이드인 → 페이드아웃
    af = (
        f"afade=t=in:st=0:d={FADE_IN_AUDIO},"
        f"afade=t=out:st={fade_out_audio_start:.1f}:d={FADE_OUT_AUDIO}"
    )

    cmd = [
        "ffmpeg",
        "-loop", "1",
        "-i", image_path,
        "-stream_loop", "-1",
        "-i", audio_path,
        "-c:v", "libx264",
        "-tune", "stillimage",
        "-preset", "fast",         # 인코딩 속도 개선 (slow → fast)
        "-c:a", "aac",
        "-b:v", "800k",            # 500k → 800k (화질 개선)
        "-b:a", "192k",            # 128k → 192k (음질 개선)
        "-pix_fmt", "yuv420p",
        "-vf", vf,
        "-af", af,
        "-t", str(duration_seconds),
        "-shortest",
        "-movflags", "+faststart",  # 웹 스트리밍 최적화 (재생 빠르게 시작)
        "-y",
        output_path
    ]

    print(f"렌더링 중: {Path(output_path).name}")
    print(f"  페이드인 — 영상 {FADE_IN_VIDEO}s / 오디오 {FADE_IN_AUDIO}s")
    print(f"  페이드아웃 — 영상 {FADE_OUT_VIDEO}s / 오디오 {FADE_OUT_AUDIO}s")

    result = subprocess.run(
        cmd, capture_output=True, text=True,
        encoding="utf-8", errors="ignore"
    )
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg 오류: {result.stderr[-500:]}")

    size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"완료: {size_mb:.1f}MB")
    return output_path


def batch_create_videos(music_folder, thumbnail_folder, output_folder):
    music_files = sorted(Path(music_folder).glob("*.mp3"))
    thumbnails  = sorted(Path(thumbnail_folder).glob("*.png"))

    if not music_files:
        print(f"⚠️  음악 파일 없음: {music_folder}")
        return 0
    if not thumbnails:
        print(f"⚠️  썸네일 없음: {thumbnail_folder}")
        return 0

    os.makedirs(output_folder, exist_ok=True)

    for i, music_file in enumerate(music_files):
        thumb  = thumbnails[i % len(thumbnails)]
        output = Path(output_folder) / f"{music_file.stem}.mp4"
        print(f"\n[{i+1}/{len(music_files)}] {music_file.name}")
        try:
            create_lofi_video(
                audio_path=str(music_file),
                image_path=str(thumb),
                output_path=str(output),
                duration_hours=1.0
            )
        except Exception as e:
            print(f"  ❌ 오류: {e}")

    return len(music_files)


if __name__ == "__main__":
    count = batch_create_videos(
        music_folder="music/",
        thumbnail_folder="assets/thumbnails/",
        output_folder="output/"
    )
    print(f"\n총 {count}개 영상 생성 완료")