"""
autopublish.py · GitHub Actions 진입점 — 준비된 릴리스를 찾아 렌더 + J_Jlaylist 업로드
──────────────────────────────────────────────────────────────
'준비됨' = plan.json의 모든 곡에 audio가 있고 파일이 존재 + art/cover.* 존재
- 영상/쇼츠 파일은 git에 올리지 않으므로 필요할 때마다 여기서 렌더
- 하루 업로드 한도를 릴리스들에 순서대로 배분 (오래된 릴리스 먼저)

  python autopublish.py               # 전체 자동
  python autopublish.py --slug xxx    # 특정 릴리스만
  python autopublish.py --dry-run
  python autopublish.py --prepare     # 렌더만 + 승인 요청 요약(pending.json) 작성
  python autopublish.py --approved-only  # 이미 승인된 릴리스의 남은 쇼츠만 업로드
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
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--approved-only", action="store_true")
    a = ap.parse_args()
    dirs = [RELEASES_DIR / a.slug] if a.slug else sorted(
        (x for x in RELEASES_DIR.glob("*") if x.is_dir()),
        key=lambda x: json.loads((x / "plan.json").read_text(encoding="utf-8")).get("created", "") if (x / "plan.json").exists() else "")
    todo = [d for d in dirs if ready(d)]
    load = lambda d: json.loads((d / "plan.json").read_text(encoding="utf-8"))
    if a.approved_only:
        todo = [d for d in todo if load(d).get("approved")]
    if not todo:
        print("::RESULT::NOTHING_TO_DO")
        if a.prepare:
            json.dump({"needs_approval": False, "approved_pending": False, "releases": []}, open("pending.json", "w"))
        return
    if a.prepare:
        return prepare(todo, load)
    yt = None if a.dry_run else publish.youtube()
    budget, total = a.max_uploads, 0
    for d in todo:
        if budget <= 0:
            break
        if not (d / "video" / "full_album.mp4").exists() or not any((d / "shorts").glob("*.mp4")):
            subprocess.run([sys.executable, "render_album.py", "--slug", d.name], check=True)
        if not a.dry_run:                      # 이 job까지 왔다면 승인된 것
            plan = load(d); plan["approved"] = True
            (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        n = publish.publish_release(d.name, yt, budget, None, a.dry_run)
        budget -= n; total += n
    print(f"::RESULT::UPLOADED_{total}")

def prepare(todo, load):
    """렌더하고, 승인이 필요한 릴리스 요약을 pending.json으로 남긴다 (Slack 알림용)."""
    import datetime as dt
    out = []
    for d in todo:
        if not (d / "video" / "full_album.mp4").exists() or not any((d / "shorts").glob("*.mp4")):
            subprocess.run([sys.executable, "render_album.py", "--slug", d.name], check=True)
        plan = load(d); log = plan.get("youtube", {})
        album_at = log.get("album_at") or publish.next_slot(dt.datetime.now(publish.KST)).isoformat()
        out.append({"slug": d.name, "album": plan["album_title"], "approved": bool(plan.get("approved")),
                    "album_uploaded": bool(log.get("album")), "album_at": album_at[:16].replace("T", " "),
                    "tracks": [{"no": t["no"], "title": t["title"], "hook": t.get("hook_line", ""),
                                "take": t.get("take", ""), "dur": t.get("duration", 0),
                                "short_done": bool(log.get(f"short_{t['no']}"))} for t in plan["tracks"]]})
    res = {"needs_approval": any(not r["approved"] for r in out),
           "approved_pending": any(r["approved"] for r in out), "releases": out}
    json.dump(res, open("pending.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"::RESULT::PREPARED_{len(out)}")

if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
