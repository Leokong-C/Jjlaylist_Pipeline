"""
publish.py · STEP 5 — J_Jlaylist 채널 업로드 (AI 합성 콘텐츠 표시 자동)
──────────────────────────────────────────────────────────────
- 업로드 전에 인증된 채널이 J_Jlaylist(@J_Jlaylist)인지 확인, 다르면 중단
- 풀앨범: 다음날 21:00 KST 예약 공개 (--publish-at으로 변경)
- 쇼츠:   풀앨범 공개 다음날부터 하루 1개씩 21:00 예약
- 하루 업로드 한도(기본 6개, YouTube 쿼터 10,000 / 업로드 1,600) 초과분은 다음 실행 때 이어서
- 업로드 결과(video id)는 plan.json의 youtube 항목에 기록 → 중복 업로드 없음

사용법:
  python publish.py --slug <slug> --dry-run
  python publish.py --slug <slug>
  python publish.py --slug <slug> --publish-at 2026-12-05T21:00
  (GitHub Actions에서는 autopublish.py가 자동 호출)
"""
import argparse, base64, json, os, pickle, datetime as dt, yaml
from config import BIBLE_FILE, TOKEN_PATH, SECRET_FILE, release_dir

KST = dt.timezone(dt.timedelta(hours=9))
SCOPES = ["https://www.googleapis.com/auth/youtube"]
CHANNEL_ID = os.getenv("YT_CHANNEL_ID", "UCYuOzLTEVZX7frX-jqlmeMA")   # @J_Jlaylist
PUBLISH_HOUR = int(os.getenv("PUBLISH_HOUR_KST", "21"))

def youtube():
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    b64 = os.getenv("TOKEN_PICKLE_B64")
    if b64:                                   # GitHub Actions
        creds = pickle.loads(base64.b64decode(b64))
    elif TOKEN_PATH.exists():
        creds = pickle.loads(TOKEN_PATH.read_bytes())
    else:
        from google_auth_oauthlib.flow import InstalledAppFlow
        creds = InstalledAppFlow.from_client_secrets_file(str(SECRET_FILE), SCOPES).run_local_server(port=0)
    if not creds.valid and creds.refresh_token:
        creds.refresh(Request())
    if not b64:
        TOKEN_PATH.write_bytes(pickle.dumps(creds))
    yt = build("youtube", "v3", credentials=creds)
    ch = yt.channels().list(part="snippet", mine=True).execute()["items"][0]
    if ch["id"] != CHANNEL_ID:
        raise SystemExit(f"❌ 인증된 채널이 다릅니다: {ch['snippet']['title']} ({ch['id']})")
    print(f"🔐 채널 확인: {ch['snippet']['title']}")
    return yt

def next_slot(after: dt.datetime) -> dt.datetime:
    slot = (after + dt.timedelta(days=1)).astimezone(KST).replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
    return slot

def body(title, desc, tags, when):
    return {"snippet": {"title": title[:100], "description": desc[:5000], "tags": tags,
                        "categoryId": "10", "defaultLanguage": "ko", "defaultAudioLanguage": "ko"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                       "containsSyntheticMedia": True,
                       "publishAt": when.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}}

def upload(yt, path, b, thumb=None, dry=False):
    if dry:
        print(f"   [DRY] {b['snippet']['title']}  → {b['status']['publishAt']}")
        return "DRY_RUN"
    from googleapiclient.http import MediaFileUpload
    req = yt.videos().insert(part="snippet,status", body=b,
                             media_body=MediaFileUpload(str(path), chunksize=-1, resumable=True))
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    vid = resp["id"]
    if thumb and Path(thumb).exists():
        try:
            yt.thumbnails().set(videoId=vid, media_body=MediaFileUpload(str(thumb))).execute()
        except Exception as e:
            print(f"   ⚠️ 썸네일 실패(채널 인증 필요할 수 있음): {e}")
    print(f"   ✅ https://youtu.be/{vid}  ({b['status']['publishAt']})")
    return vid

def publish_release(slug, yt, budget=6, publish_at=None, dry=False) -> int:
    """업로드한 개수를 반환. plan.json에 진행 상황 기록."""
    d = release_dir(slug)
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    bible = yaml.safe_load(BIBLE_FILE.read_text(encoding="utf-8"))
    project = bible["project"]["name"]
    fmt = bible.get("release", {}).get("youtube_title_format", "[FULL ALBUM] {project} - {album}")
    tags = [project, bible["project"].get("name_en", ""), plan["album_title"], "인디밴드", "플레이리스트"]
    log = plan.setdefault("youtube", {})
    used = 0
    if not log.get("album") and used < budget:
        when = publish_at or next_slot(dt.datetime.now(KST))
        print(f"▶ [{slug}] 풀앨범")
        log["album"] = upload(yt, d / "video" / "full_album.mp4",
                              body(fmt.format(project=project, album=plan["album_title"]),
                                   (d / "video" / "description.txt").read_text(encoding="utf-8"), tags, when),
                              d / "video" / "thumbnail.jpg", dry)
        log["album_at"] = when.isoformat(); used += 1
    if log.get("album"):
        base = dt.datetime.fromisoformat(log["album_at"])
        for i, t in enumerate(plan["tracks"], 1):
            key = f"short_{t['no']}"
            if log.get(key) or not t.get("short"):
                continue
            if used >= budget:
                print(f"   ⏸ 일일 한도 도달 — 남은 쇼츠는 다음 실행에서 업로드"); break
            print(f"▶ [{slug}] 쇼츠 {t['no']:02d}")
            desc = (f"{t.get('shorts_caption','')}\n\n풀앨범: https://youtu.be/{log['album']}\n"
                    f"#shorts #{project.replace(' ','')}")
            log[key] = upload(yt, d / t["short"]["file"],
                              body(f"{t['hook_line']} | {project} - {t['title']}", desc, tags,
                                   base + dt.timedelta(days=i)), None, dry)
            used += 1
    if not dry:
        (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return used

def fully_published(plan) -> bool:
    log = plan.get("youtube", {})
    return bool(log.get("album")) and all(log.get(f"short_{t['no']}") for t in plan["tracks"] if t.get("short"))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--publish-at", help="KST, 예: 2026-12-05T21:00")
    ap.add_argument("--max-uploads", type=int, default=6)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    when = dt.datetime.fromisoformat(a.publish_at).replace(tzinfo=KST) if a.publish_at else None
    yt = None if a.dry_run else youtube()
    publish_release(a.slug, yt, a.max_uploads, when, a.dry_run)

from pathlib import Path
if __name__ == "__main__":
    main()
