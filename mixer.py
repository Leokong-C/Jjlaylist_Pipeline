"""
mixer.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
10곡 크로스페이드 믹스 MP4 자동 생성

사용법:
  python mixer.py --mood night       # 밤·드라이브 테마
  python mixer.py --mood cafe        # 카페·비 테마
  python mixer.py --mood melancholy  # 이별·추억 테마
  python mixer.py --mood dawn        # 새벽·아침 테마
  python mixer.py --count 4         # 4개 연속
  python mixer.py --songs 8         # 곡 수 변경
"""

import subprocess, os, json, random, re, argparse
from pathlib import Path

# ── 경로 ─────────────────────────────────────────────────────────────────
BASE_DIR   = Path(__file__).parent
MUSIC_DIR  = BASE_DIR / "music"
THUMB_DIR  = BASE_DIR / "assets" / "thumbnails"
OUTPUT_DIR = BASE_DIR / "output" / "mixes"
TEMP_DIR   = BASE_DIR / "output" / "temp"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
TEMP_DIR.mkdir(parents=True, exist_ok=True)

# ── 설정 ─────────────────────────────────────────────────────────────────
SONGS_PER_MIX  = 10
CROSSFADE_SEC  = 3
FADE_IN_SEC    = 1.5
FADE_OUT_SEC   = 4.0
VIDEO_BITRATE  = "800k"
AUDIO_BITRATE  = "192k"

# ── 분위기 키워드 ─────────────────────────────────────────────────────────
MOOD_KEYWORDS = {
    "night":      ["midnight", "neon", "night", "택시", "taxi", "2am", "3am",
                   "신호", "네온", "도시", "rain", "shibuya"],
    "cafe":       ["coffee", "cafe", "카페", "비", "rain", "window", "창가",
                   "still warm", "convenience", "편의점", "morning without"],
    "melancholy": ["alone", "cassette", "shirt", "이별", "혼자", "goodbye",
                   "last", "sent", "love", "not over", "regret", "passed"],
    "dawn":       ["dawn", "morning", "sunrise", "새벽", "fm", "radio",
                   "1_12", "page", "2am", "3am"],
}

MOOD_TITLES = {
    "night":      "TOKYO NIGHT DRIVE MIX",
    "cafe":       "CITY POP RAIN MIX",
    "melancholy": "JAPANESE LOFI MIX",
    "dawn":       "DAWN CITY POP MIX",
    "all":        "JAPANESE CITY POP MIX",
}

MOOD_EMOJI = {
    "night": "🌙", "cafe": "☕",
    "melancholy": "🎧", "dawn": "🌅", "all": "🎧",
}

# ── 폴백 배경색 (썸네일 없을 때) ─────────────────────────────────────────
FALLBACK_BG_COLOR = "0x0a0a1a"   # 짙은 네이비


def get_duration(mp3_path: str) -> float:
    cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration",
           "-of", "json", str(mp3_path)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return 240.0


def select_songs(mood: str, n: int, used: set = None) -> list:
    if used is None:
        used = set()
    all_mp3 = [f for f in MUSIC_DIR.glob("*.mp3") if f.name not in used]
    if mood != "all" and mood in MOOD_KEYWORDS:
        kws     = MOOD_KEYWORDS[mood]
        matched = [f for f in all_mp3
                   if any(kw.lower() in f.stem.lower() for kw in kws)]
        others  = [f for f in all_mp3 if f not in matched]
        random.shuffle(matched)
        random.shuffle(others)
        pool = matched + others
    else:
        pool = list(all_mp3)
        random.shuffle(pool)
    return pool[:n]


def mix_audio_crossfade(songs: list, output_audio: Path) -> tuple:
    """
    N개 MP3 → 크로스페이드 오디오
    반환: (timestamps, total_sec)
    """
    n         = len(songs)
    durations = [get_duration(str(s)) for s in songs]

    # 타임스탬프 계산
    timestamps, cur = [], 0.0
    for i, (song, dur) in enumerate(zip(songs, durations)):
        timestamps.append((song.stem, cur))
        cur += dur - (CROSSFADE_SEC if i < n - 1 else 0)
    total = cur

    # FFmpeg 입력
    inputs = []
    for s in songs:
        inputs += ["-i", str(s)]

    # ── filter_complex 구성 ──
    fade_out_start = max(0.0, total - FADE_OUT_SEC)

    if n == 1:
        fc = (f"[0:a]afade=t=in:st=0:d={FADE_IN_SEC},"
              f"afade=t=out:st={fade_out_start:.2f}:d={FADE_OUT_SEC}"
              f"[aout]")

    elif n == 2:
        # [0][1] → crossfade → [cf01] → fade in/out → [aout]
        fc = (f"[0:a][1:a]acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri[cf01];"
              f"[cf01]afade=t=in:st=0:d={FADE_IN_SEC},"
              f"afade=t=out:st={fade_out_start:.2f}:d={FADE_OUT_SEC}"
              f"[aout]")

    else:
        # n >= 3: [0][1]→[cf01], [cf01][2]→[cf012], ..., [cfXX]→fade→[aout]
        parts = []
        prev  = "cf01"
        parts.append(
            f"[0:a][1:a]acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri[{prev}]"
        )
        for i in range(2, n):
            cur_lbl = f"cf{''.join(str(x) for x in range(i+1))}"
            # 라벨이 너무 길어지면 단순 인덱스로
            cur_lbl = f"cf{i:02d}"
            parts.append(
                f"[{prev}][{i}:a]"
                f"acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri"
                f"[{cur_lbl}]"
            )
            prev = cur_lbl

        # 마지막 라벨에 페이드인/아웃
        parts.append(
            f"[{prev}]afade=t=in:st=0:d={FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={FADE_OUT_SEC}"
            f"[aout]"
        )
        fc = ";".join(parts)

    cmd = (["ffmpeg"] + inputs +
           ["-filter_complex", fc,
            "-map", "[aout]",
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            "-y", str(output_audio)])

    print("  🎚  오디오 크로스페이드 믹싱 중...")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"오디오 믹싱 실패:\n{r.stderr[-500:]}")

    return timestamps, total


def render_video(audio: Path, thumb, out: Path, duration: float):
    """
    thumb: Path 또는 None (None이면 단색 배경으로 폴백)
    """
    vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:(ow-iw)/2:(oh-ih)/2")

    if thumb and Path(thumb).exists():
        video_input = ["-loop", "1", "-i", str(thumb)]
    else:
        # 썸네일 없을 때 단색 배경
        video_input = [
            "-f", "lavfi",
            "-i", f"color=c={FALLBACK_BG_COLOR}:size=1920x1080:rate=1"
        ]

    cmd = (["ffmpeg"] +
           video_input +
           ["-i", str(audio),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-preset", "fast",
            "-c:a", "copy",
            "-b:v", VIDEO_BITRATE,
            "-pix_fmt", "yuv420p",
            "-vf", vf,
            "-t", str(int(duration)),
            "-shortest",
            "-movflags", "+faststart",
            "-y", str(out)])

    print("  🎬  비디오 렌더링 중...")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"비디오 렌더링 실패:\n{r.stderr[-500:]}")


def format_timestamps(timestamps: list) -> str:
    lines = ["🎵 Tracklist\n"]
    for i, (name, sec) in enumerate(timestamps, 1):
        m, s  = int(sec) // 60, int(sec) % 60
        clean = re.sub(r"^\d+[\. ]+", "", name)
        clean = re.sub(r"\s*\(\d+\)\s*$", "", clean).strip()
        lines.append(f"{m:02d}:{s:02d}  {clean}")
    return "\n".join(lines)


def pick_thumbnail(mood: str, seed: int):
    """분위기 폴더에서 썸네일 선택. 없으면 None 반환."""
    rng    = random.Random(seed)
    exts   = ["*.png", "*.jpg", "*.jpeg"]
    thumbs = sorted([
        f for ext in exts for f in THUMB_DIR.glob(ext)
        if "auto" not in str(f).lower()
    ])
    if not thumbs:
        thumbs = list(THUMB_DIR.rglob("*.png"))
    if not thumbs:
        return None

    pref_kw = {
        "night":      ["차량내부", "car"],
        "cafe":       ["소녀", "girl"],
        "melancholy": ["커플", "우주인"],
        "dawn":       ["우주인"],
        "all":        [],
    }
    preferred = [t for t in thumbs
                 if any(k in t.name for k in pref_kw.get(mood, []))]
    pool = preferred or thumbs
    return rng.choice(pool)


def create_mix(mood: str = "all", songs_n: int = SONGS_PER_MIX,
               mix_index: int = 1, used_songs: set = None) -> dict:
    if used_songs is None:
        used_songs = set()

    print(f"\n{'='*60}")
    print(f"믹스 #{mix_index:02d} | 테마: {mood.upper()} | {songs_n}곡")
    print("=" * 60)

    songs = select_songs(mood, songs_n, used_songs)
    if len(songs) < 2:
        raise ValueError(f"선택 가능한 곡 부족: {len(songs)}개 (최소 2곡)")

    print("선택된 곡:")
    for i, s in enumerate(songs, 1):
        clean = re.sub(r"\s*\(\d+\)\s*$", "", s.stem).strip()
        print(f"  {i:2d}. {clean}")

    temp_audio = TEMP_DIR / f"mix_{mix_index:02d}_{mood}.m4a"
    timestamps, total_dur = mix_audio_crossfade(songs, temp_audio)

    thumb = pick_thumbnail(mood, seed=mix_index * 77)
    print(f"  🖼  썸네일: {thumb.name if thumb else '없음 (단색 폴백)'}")

    label    = MOOD_TITLES.get(mood, "JAPANESE CITY POP MIX")
    out_name = f"{label} #{mix_index:02d}.mp4"
    out_path = OUTPUT_DIR / out_name

    render_video(temp_audio, thumb, out_path, total_dur)
    temp_audio.unlink(missing_ok=True)

    ts_str = format_timestamps(timestamps)
    size   = out_path.stat().st_size / (1024 * 1024)
    print(f"\n✅ {out_name}  ({size:.1f}MB, {total_dur/60:.1f}분)")
    print(f"\n{ts_str}")

    for s in songs:
        used_songs.add(s.name)

    return {
        "output":       str(out_path),
        "mood":         mood,
        "mix_index":    mix_index,
        "label":        label,
        "emoji":        MOOD_EMOJI.get(mood, "🎧"),
        "timestamps":   ts_str,
        "duration_min": total_dur / 60,
        "songs":        [s.name for s in songs],
        "thumbnail":    str(thumb) if thumb else None,
    }


# ── 하위 호환 함수 ────────────────────────────────────────────────────────
def mix_with_timestamps(music_folder="music/", thumbnail_path=None,
                        output_path="output/mixed_playlist.mp4",
                        track_count=10, shuffle=True) -> dict:
    result = create_mix(mood="all", songs_n=track_count, mix_index=1)
    return {"output": result["output"], "timestamps": result["timestamps"]}


def mix_tracks(music_folder="music/", thumbnail_path=None,
               output_path="output/mixed_playlist.mp4",
               track_count=10, target_hours=1.0, shuffle=True):
    result = create_mix(mood="all", songs_n=track_count, mix_index=1)
    return result["output"]


def main():
    p = argparse.ArgumentParser(description="J_Jlaylist 믹스 생성기")
    p.add_argument("--mood",  default="all",
                   choices=["night", "cafe", "melancholy", "dawn", "all"])
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--songs", type=int, default=SONGS_PER_MIX)
    p.add_argument("--start", type=int, default=1)
    args = p.parse_args()

    if args.mood == "all" and args.count > 1:
        moods = (["night", "cafe", "melancholy", "dawn"] * args.count)[:args.count]
    else:
        moods = [args.mood] * args.count

    used, results = set(), []
    for i, mood in enumerate(moods):
        idx = args.start + i
        try:
            r = create_mix(mood=mood, songs_n=args.songs,
                           mix_index=idx, used_songs=used)
            results.append(r)
        except Exception as e:
            print(f"❌ 믹스 #{idx} 실패: {e}")

    print(f"\n완료: {len(results)}개 → {OUTPUT_DIR}")
    return results


if __name__ == "__main__":
    main()