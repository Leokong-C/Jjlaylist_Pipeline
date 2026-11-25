"""
ingest.py · STEP 3 — 곡 입고(Mureka 후보 선택 또는 직접 넣은 파일) + 라우드니스 정규화
──────────────────────────────────────────────────────────────
inbox/<slug>/NN_*.mp3(또는 .wav) → releases/<slug>/audio/NN.mp3 (-14 LUFS, 320k)
plan.json의 각 트랙에 파일 경로·길이를 기록합니다.

사용법:
  python ingest.py --slug <slug>                    # inbox/<slug>/NN_*.mp3 직접 넣은 경우
  python ingest.py --slug <slug> --pick "1a,2b,3a"  # Mureka 후보 중 선택
  python ingest.py --slug <slug> --auto             # 후보 a로 일괄 선택
"""
import argparse, json, re, subprocess
from config import INBOX_DIR, FFMPEG, FFPROBE, TARGET_LUFS, release_dir

def duration(path) -> float:
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    return float(out.stdout.strip())

def normalize(src, dst) -> None:
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", str(src),
                    "-af", f"loudnorm=I={TARGET_LUFS}:TP=-1.0:LRA=11", "-ar", "44100",
                    "-b:a", "320k", str(dst)], check=True)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--slug", required=True)
    ap.add_argument("--pick", default=""); ap.add_argument("--auto", action="store_true")
    a = ap.parse_args(); slug = a.slug
    d = release_dir(slug)
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    inbox = INBOX_DIR / slug; inbox.mkdir(parents=True, exist_ok=True)
    files = {int(m.group(1)): f for f in sorted(inbox.iterdir())
             if f.suffix.lower() in (".mp3", ".wav", ".m4a") and (m := re.match(r"(\d+)", f.name))}
    cand = inbox / "candidates"
    picks = {int(p[:-1]): p[-1] for p in a.pick.replace(" ", "").split(",") if p}
    for t in plan["tracks"]:
        ch = picks.get(t["no"]) or ("a" if a.auto else None)
        c = cand / f"{t['no']:02d}_{ch}.mp3" if ch else None
        if c and c.exists():
            files[t["no"]] = c; t["take"] = ch
    missing = []
    for t in plan["tracks"]:
        src = files.get(t["no"])
        if not src:
            missing.append(t["no"]); continue
        dst = d / "audio" / f"{t['no']:02d}.mp3"
        normalize(src, dst)
        t["audio"] = str(dst.relative_to(d)); t["duration"] = round(duration(dst), 2)
        print(f"  ✅ {t['no']:02d}. {t['title']}  ({t['duration']:.0f}s)")
    (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    if missing:
        print(f"⚠️  inbox/{slug}/ 에 없는 곡 번호: {missing}")
    else:
        print("✅ 전 곡 입고 완료 → python render_album.py --slug", slug)

if __name__ == "__main__":
    main()
