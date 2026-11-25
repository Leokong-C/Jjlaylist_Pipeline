"""
render_album.py · STEP 4 — 풀앨범 영상 + 챕터 설명란 + 곡별 쇼츠
──────────────────────────────────────────────────────────────
필요: releases/<slug>/art/cover.(png|jpg)  ← 직접 만든 커버 (없으면 임시 커버 생성)

출력:
  video/full_album.mp4     16:9, 곡마다 '현재 곡' 표시가 바뀌는 정지화면 영상
  video/description.txt    콘셉트 + 챕터 타임스탬프 + AI 사용 고지
  video/thumbnail.jpg
  shorts/NN.mp4            9:16, 후렴 30초 + hook_line 자막

사용법:
  python render_album.py --slug <slug>
  python render_album.py --slug <slug> --no-shorts
  python render_album.py --slug <slug> --hook "1:62,3:48"   # 곡별 쇼츠 시작초 지정
"""
import argparse, json, subprocess, yaml
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont
from config import BIBLE_FILE, FFMPEG, font_path, release_dir

W, H = 1920, 1080
SW, SH = 1080, 1920

def ts(sec: float) -> str:
    s = int(sec); h, m = divmod(s, 3600); m, s = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

def load_cover(d: Path, plan: dict) -> Image.Image:
    for ext in ("png", "jpg", "jpeg", "webp"):
        p = d / "art" / f"cover.{ext}"
        if p.exists():
            return Image.open(p).convert("RGB")
    print("⚠️  art/cover.* 없음 → 임시 커버 생성 (업로드 전 교체 권장)")
    img = Image.new("RGB", (1500, 1500), (16, 24, 48))
    dr = ImageDraw.Draw(img)
    dr.text((750, 750), plan["album_title"], font=ImageFont.truetype(font_path(), 90),
            fill=(220, 240, 235), anchor="mm")
    img.save(d / "art" / "cover.png")
    return img

def fit(img, w, h):
    r = max(w / img.width, h / img.height)
    img = img.resize((int(img.width * r) + 1, int(img.height * r) + 1), Image.LANCZOS)
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))

def wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > max_w and cur:
            lines.append(cur); cur = ch
        else:
            cur += ch
    return lines + [cur]

def album_frame(cover, plan, project, idx) -> Image.Image:
    bg = fit(cover, W, H).filter(ImageFilter.GaussianBlur(40))
    bg = Image.blend(bg, Image.new("RGB", (W, H), (0, 0, 0)), 0.45)
    side = 760
    bg.paste(cover.resize((side, side), Image.LANCZOS), (140, (H - side) // 2))
    dr = ImageDraw.Draw(bg)
    fp = font_path()
    f_big, f_mid, f_small = (ImageFont.truetype(fp, s) for s in (58, 34, 30))
    x = 140 + side + 90; y = 190
    dr.text((x, y), project, font=f_small, fill=(180, 200, 200)); y += 55
    for line in wrap(dr, plan["album_title"], f_big, W - x - 100):
        dr.text((x, y), line, font=f_big, fill="white"); y += 72
    y += 30
    for i, t in enumerate(plan["tracks"]):
        on = i == idx
        txt = f"{'▶ ' if on else '   '}{t['no']:02d}  {t['title']}"
        txt = wrap(dr, txt, f_mid, W - x - 100)[0]
        dr.text((x, y), txt, font=f_mid, fill=(255, 255, 255) if on else (150, 160, 165)); y += 58
    return bg

def short_frame(cover, project, track) -> Image.Image:
    bg = fit(cover, SW, SH).filter(ImageFilter.GaussianBlur(35))
    bg = Image.blend(bg, Image.new("RGB", (SW, SH), (0, 0, 0)), 0.4)
    side = 900
    bg.paste(cover.resize((side, side), Image.LANCZOS), ((SW - side) // 2, 380))
    dr = ImageDraw.Draw(bg); fp = font_path()
    f_hook, f_t = ImageFont.truetype(fp, 64), ImageFont.truetype(fp, 40)
    y = 1360
    for line in wrap(dr, track.get("hook_line", ""), f_hook, SW - 140):
        dr.text((SW // 2, y), line, font=f_hook, fill="white", anchor="ma"); y += 84
    dr.text((SW // 2, 1720), f"{project} · {track['title']}", font=f_t, fill=(200, 210, 210), anchor="ma")
    return bg

def run(cmd):
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", *cmd], check=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--no-shorts", action="store_true")
    ap.add_argument("--hook", default="", help="곡번호:시작초,... (기본: 곡 길이의 40%%)")
    ap.add_argument("--short-len", type=int, default=30)
    a = ap.parse_args()
    d = release_dir(a.slug)
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    bible = yaml.safe_load(BIBLE_FILE.read_text(encoding="utf-8"))
    project = bible["project"]["name"]
    tracks = [t for t in plan["tracks"] if t.get("audio")]
    if len(tracks) != len(plan["tracks"]):
        raise SystemExit("입고 안 된 곡이 있습니다. ingest.py 먼저 실행하세요.")
    cover = load_cover(d, plan)
    tmp = d / "video" / "_frames"; tmp.mkdir(exist_ok=True)

    # 1) 곡별 프레임 + concat 리스트
    lst, chapters, t0 = [], [], 0.0
    for i, t in enumerate(tracks):
        fpath = tmp / f"{t['no']:02d}.png"
        album_frame(cover, plan, project, i).save(fpath)
        lst += [f"file '{fpath.as_posix()}'", f"duration {t['duration']}"]
        chapters.append(f"{ts(t0)} {t['no']:02d}. {t['title']}")
        t0 += t["duration"]
    lst.append(f"file '{(tmp / f'{tracks[-1]['no']:02d}.png').as_posix()}'")
    (tmp / "frames.txt").write_text("\n".join(lst), encoding="utf-8")
    (tmp / "audio.txt").write_text("\n".join(f"file '{(d / t['audio']).as_posix()}'" for t in tracks), encoding="utf-8")

    # 2) 풀앨범 영상 (정지화면 → 인코딩 가벼움)
    full = d / "video" / "full_album.mp4"
    run(["-f", "concat", "-safe", "0", "-i", str(tmp / "frames.txt"),
         "-f", "concat", "-safe", "0", "-i", str(tmp / "audio.txt"),
         "-vf", "fps=2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
         "-tune", "stillimage", "-crf", "20", "-c:a", "aac", "-b:a", "256k",
         "-shortest", "-movflags", "+faststart", str(full)])
    album_frame(cover, plan, project, -1).convert("RGB").save(d / "video" / "thumbnail.jpg", quality=92)

    # 3) 설명란
    tl = "\n".join(chapters)
    desc = (f"{plan['concept']}\n\n🎧 Tracklist\n{tl}\n\n"
            f"ℹ️ {bible['project'].get('ai_disclosure','')}\n\n"
            f"#{project.replace(' ', '')} #인디밴드 #플레이리스트")
    (d / "video" / "description.txt").write_text(desc, encoding="utf-8")
    print(f"✅ 풀앨범 영상 → {full}  ({ts(t0)})")

    # 4) 쇼츠
    if a.no_shorts:
        return
    hooks = {int(k): float(v) for k, v in (p.split(":") for p in a.hook.split(",") if p)}
    for t in tracks:
        prev = (t.get("short") or {}).get("start")          # 이전에 정한 구간 유지 (CI 재렌더 대비)
        start = hooks.get(t["no"], prev if prev is not None else round(t["duration"] * 0.4, 1))
        start = max(0, min(start, t["duration"] - a.short_len))
        fimg = tmp / f"short_{t['no']:02d}.png"
        short_frame(cover, project, t).save(fimg)
        out = d / "shorts" / f"{t['no']:02d}.mp4"
        L = a.short_len
        run(["-loop", "1", "-framerate", "2", "-i", str(fimg),
             "-ss", str(start), "-t", str(L), "-i", str(d / t["audio"]),
             "-af", f"afade=t=in:d=0.5,afade=t=out:st={L-1.5}:d=1.5",
             "-vf", "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-tune", "stillimage",
             "-c:a", "aac", "-b:a", "192k", "-t", str(L), "-movflags", "+faststart", str(out)])
        t["short"] = {"file": str(out.relative_to(d)), "start": start}
        print(f"  🎬 쇼츠 {t['no']:02d} ({start:.0f}s~)")
    (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
