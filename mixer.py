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
  python mixer.py --offset 30       # 각 트랙 앞 30초 스킵 (인트로 스킵)
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
START_OFFSET   = 0   # 기본값: 스킵 없음 (main()에서 덮어씀)

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
FALLBACK_BG_COLOR = "0x0a0a1a"


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
    seen_stems = set()
    deduped = []
    for f in pool:
        stem = f.stem.replace(" (1)", "").replace("(1)", "").strip()
        if stem not in seen_stems:
            seen_stems.add(stem)
            deduped.append(f)
    return deduped[:n]


def mix_audio_crossfade(songs: list, output_audio: Path,
                        start_offset: int = 0) -> tuple:
    """
    N개 MP3 → 크로스페이드 오디오
    start_offset: 각 트랙 앞부분 스킵할 초 (인트로 스킵용)
    반환: (timestamps, total_sec)
    """
    n        = len(songs)
    raw_durs = [get_duration(str(s)) for s in songs]
    durations = [max(0.0, d - start_offset) for d in raw_durs]

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

    # ── 오프셋 트림 필터 ──
    def trim(idx):
        if start_offset > 0:
            return (f"[{idx}:a]atrim=start={start_offset},"
                    f"asetpts=PTS-STARTPTS[a{idx}]")
        return None

    trim_parts = [trim(i) for i in range(n) if start_offset > 0]

    def src(idx):
        return f"[a{idx}]" if start_offset > 0 else f"[{idx}:a]"

    # ── filter_complex 구성 ──
    fade_out_start = max(0.0, total - FADE_OUT_SEC)

    if n == 1:
        cf_parts = [
            f"{src(0)}afade=t=in:st=0:d={FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={FADE_OUT_SEC}[aout]"
        ]

    elif n == 2:
        cf_parts = [
            f"{src(0)}{src(1)}acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri[cf01]",
            f"[cf01]afade=t=in:st=0:d={FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={FADE_OUT_SEC}[aout]"
        ]

    else:
        cf_parts = []
        prev = "cf01"
        cf_parts.append(
            f"{src(0)}{src(1)}acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri[{prev}]"
        )
        for i in range(2, n):
            cur_lbl = f"cf{i:02d}"
            cf_parts.append(
                f"[{prev}]{src(i)}"
                f"acrossfade=d={CROSSFADE_SEC}:c1=tri:c2=tri[{cur_lbl}]"
            )
            prev = cur_lbl
        cf_parts.append(
            f"[{prev}]afade=t=in:st=0:d={FADE_IN_SEC},"
            f"afade=t=out:st={fade_out_start:.2f}:d={FADE_OUT_SEC}[aout]"
        )

    all_parts = (trim_parts if trim_parts else []) + cf_parts
    fc = ";".join(all_parts)

    cmd = (["ffmpeg"] + inputs +
           ["-filter_complex", fc,
            "-map", "[aout]",
            "-c:a", "aac",
            "-b:a", AUDIO_BITRATE,
            "-y", str(output_audio)])

    offset_msg = f" (각 트랙 앞 {start_offset}초 스킵)" if start_offset > 0 else ""
    print(f"  🎚  오디오 크로스페이드 믹싱 중...{offset_msg}")
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="ignore")
    if r.returncode != 0:
        raise RuntimeError(f"오디오 믹싱 실패:\n{r.stderr[-500:]}")

    return timestamps, total


def render_video(audio: Path, thumb, out: Path, duration: float):
    vf = ("scale=1920:1080:force_original_aspect_ratio=decrease,"
          "pad=1920:1080:(ow-iw)/2:(oh-ih)/2")

    if thumb and Path(thumb).exists():
        video_input = ["-loop", "1", "-i", str(thumb)]
    else:
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
               mix_index: int = 1, used_songs: set = None,
               start_offset: int = 0) -> dict:
    if used_songs is None:
        used_songs = set()

    print(f"\n{'='*60}")
    offset_info = f" | 인트로 {start_offset}초 스킵" if start_offset > 0 else ""
    print(f"믹스 #{mix_index:02d} | 테마: {mood.upper()} | {songs_n}곡{offset_info}")
    print("=" * 60)

    songs = select_songs(mood, songs_n, used_songs)
    if len(songs) < 2:
        raise ValueError(f"선택 가능한 곡 부족: {len(songs)}개 (최소 2곡)")

    print("선택된 곡:")
    for i, s in enumerate(songs, 1):
        clean = re.sub(r"\s*\(\d+\)\s*$", "", s.stem).strip()
        print(f"  {i:2d}. {clean}")

    temp_audio = TEMP_DIR / f"mix_{mix_index:02d}_{mood}.m4a"
    timestamps, total_dur = mix_audio_crossfade(songs, temp_audio,
                                                start_offset=start_offset)

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
    global START_OFFSET
    p = argparse.ArgumentParser(description="J_Jlaylist 믹스 생성기")
    p.add_argument("--mood",   default="all",
                   choices=["night", "cafe", "melancholy", "dawn", "all"])
    p.add_argument("--count",  type=int, default=1)
    p.add_argument("--songs",  type=int, default=SONGS_PER_MIX)
    p.add_argument("--start",  type=int, default=1)
    p.add_argument("--offset", type=int, default=0,
                   help="각 트랙 앞부분 스킵할 초 (기본값: 0, 권장: 30)")
    args = p.parse_args()

    START_OFFSET = args.offset
    if START_OFFSET > 0:
        print(f"⏩ 인트로 스킵 모드: 각 트랙 앞 {START_OFFSET}초 건너뜀")

    if args.mood == "all" and args.count > 1:
        moods = (["night", "cafe", "melancholy", "dawn"] * args.count)[:args.count]
    else:
        moods = [args.mood] * args.count

    used, results = set(), []
    for i, mood in enumerate(moods):
        idx = args.start + i
        try:
            r = create_mix(mood=mood, songs_n=args.songs,
                           mix_index=idx, used_songs=used,
                           start_offset=START_OFFSET)
            results.append(r)
        except Exception as e:
            print(f"❌ 믹스 #{idx} 실패: {e}")

    print(f"\n완료: {len(results)}개 → {OUTPUT_DIR}")
    return results


if __name__ == "__main__":
    main()