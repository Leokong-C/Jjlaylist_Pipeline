"""
autopublish.py · GitHub Actions 진입점 — 준비된 릴리스를 찾아 렌더 + J_Jlaylist 업로드
──────────────────────────────────────────────────────────────
'준비됨' = plan.json의 모든 곡에 audio가 있고 파일이 존재 + art/cover.* 존재
- 영상/쇼츠 파일은 git에 올리지 않으므로 필요할 때마다 여기서 렌더
- 하루 업로드 한도를 릴리스들에 순서대로 배분 (오래된 릴리스 먼저)

  python autopublish.py               # 전체 자동
  python autopublish.py --slug xxx    # 특정 릴리스만
  python autopublish.py --dry-run
"""
import argparse, json, os, subprocess, sys
from config import RELEASES_DIR
import publish

def ready(d) -> bool:
    p = d / "plan.json"
    if not p.exists():
        return False
    plan = json.loads(p.read_text(encoding="utf-8"))
    audio_ok = all(t.get("audio") and (d / t["audio"]).exists() for t in plan["tracks"])
    cover_ok = any((d / "art" / f"cover.{e}").exists() for e in ("png", "jpg", "jpeg", "webp"))
    return audio_ok and cover_ok and not publish.fully_published(plan)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug"); ap.add_argument("--max-uploads", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dirs = [RELEASES_DIR / a.slug] if a.slug else sorted(
        (x for x in RELEASES_DIR.glob("*") if x.is_dir()),
        key=lambda x: json.loads((x / "plan.json").read_text(encoding="utf-8")).get("created", "") if (x / "plan.json").exists() else "")
    todo = [d for d in dirs if ready(d)]
    if not todo:
        print("::RESULT::NOTHING_TO_DO"); return
    yt = None if a.dry_run else publish.youtube()
    budget, total = a.max_uploads, 0
    for d in todo:
        if budget <= 0:
            break
        if not (d / "video" / "full_album.mp4").exists() or not any((d / "shorts").glob("*.mp4")):
            subprocess.run([sys.executable, "render_album.py", "--slug", d.name], check=True)
        n = publish.publish_release(d.name, yt, budget, None, a.dry_run)
        budget -= n; total += n
    print(f"::RESULT::UPLOADED_{total}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
