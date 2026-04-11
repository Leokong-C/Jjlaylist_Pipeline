"""
seo_title_updater.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
수정 이력:
  v2 - 버그 수정: KeyError '이모지' (format 중괄호 충돌)
       버그 수정: 모델명 claude-sonnet-4-6 으로 변경
       개선: 제목 포맷 검증 + 재시도 로직
       개선: 태그(keywords) 동시 업데이트
       개선: 분위기별 이모지 자동 매핑

사용법:
  python seo_title_updater.py --analyze              # 채널 현황 분석
  python seo_title_updater.py --preview --scheduled  # 예약 영상 미리보기
  python seo_title_updater.py --apply --scheduled --limit 3   # 3개 테스트
  python seo_title_updater.py --apply --scheduled --use-cache # 전체 적용
  python seo_title_updater.py --restore              # 원본 복원
"""

import os, json, time, argparse, re, pickle
from pathlib import Path

import anthropic
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ── 경로 ─────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
BACKUP_FILE = BASE_DIR / "seo_backup.json"
PREVIEW_FILE= BASE_DIR / "seo_preview.json"
SCOPES      = ["https://www.googleapis.com/auth/youtube"]

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── 태그 풀 (영상마다 공통 태그 세트 적용) ───────────────────────────────
BASE_TAGS = [
    "city pop", "시티팝", "japanese city pop", "일본 시티팝",
    "lofi", "lofi hip hop", "로파이", "chill music",
    "공부 음악", "study music", "작업 음악", "드라이브 bgm",
    "카페 음악", "집중 음악", "수면 음악", "1시간", "1 hour loop",
    "j_jlaylist", "citypop bgm", "urban pop", "어반팝",
]

# ── SEO 제목 프롬프트 ─────────────────────────────────────────────────────
# ※ 중괄호 {{ }} 는 Python format() 이스케이프. 실제 출력은 { }
SEO_TITLE_PROMPT = """\
너는 J_Jlaylist 유튜브 채널의 SEO 전문가야.
채널: 일본 시티팝/Lofi 1시간 단일 트랙 루프. AI(SUNO) 생성 음악.

최고 성과 영상 기준 (103회):
  제목: [Playlist] 🎧 듣는 순간 내가 있는 곳이 어디든 일본으로 | #Citypop
  성공 요소: [Playlist] 접두사 / 경험 유발형 감성 카피 / 파이프 구분자 / 해시태그

원본 제목: {original_title}

━━ 출력 규칙 (반드시 준수) ━━
구조: [Playlist] <이모지1개> <경험표현> | <장르키워드> <시간> <용도> <해시태그>

① [Playlist] 로 시작 — 필수
② 이모지 1개만: 아래 분위기 매핑 중 가장 잘 맞는 것 하나
   - 밤/새벽/네온/드라이브 → 🌙
   - 카페/비/창가/조용함   → ☕
   - 감성/추억/이별/그리움  → 🎧
   - 도시/도쿄/여름/활기   → 🌆
   - 새벽드라이브/택시/빠름 → 🚗
③ 경험표현 (12~22자): 청자가 느끼는 장면/감각을 서술
   좋은 예: "퇴근길 창밖이 영화처럼 흘러가는"
   나쁜 예: "시티팝 플레이리스트" (장르 설명에 그침)
④ | 뒤 장르키워드: City Pop / Japanese City Pop / Lofi City Pop 중 택1
⑤ 시간: 1Hour 또는 1시간 중 하나
⑥ 용도 (선택, 1개만): 공부 / 드라이브 / 작업 / 카페 / 수면
⑦ 해시태그: #Citypop / #LofiCityPop / #일본시티팝 중 분위기 맞는 것
⑧ 전체 55~72자 이내

━━ 금지 ━━
✗ 이모지로 시작 (예: 🌙 도쿄의...)
✗ [Playlist] 없이 시작
✗ "BGM" "플레이리스트" "모음" 등 진부한 표현
✗ 두 줄 이상 출력

━━ 좋은 예시 ━━
[Playlist] 🌙 퇴근길 도시가 수채화처럼 번지는 | Japanese City Pop 1Hour #Citypop
[Playlist] ☕ 비 오는 카페 창가에서 도쿄를 떠올리는 | Lofi City Pop 공부 1Hour #LofiCityPop
[Playlist] 🎧 이별한 날 밤 혼자 걷는 긴자의 골목 | City Pop 드라이브 1시간 #일본시티팝

제목 텍스트만 출력. 설명·따옴표·마크다운 없이."""

# ── SEO 설명 프롬프트 ─────────────────────────────────────────────────────
SEO_DESC_PROMPT = """\
J_Jlaylist 유튜브 SEO 전문가야.

새 제목: {new_title}
원본 제목: {original_title}

YouTube 설명 앞부분 2줄 최적화. JSON만 출력.

line1 (38자 이내): 청자가 느끼는 감각적 한 문장. 끝에 "1시간 루프." 붙이기
line2 (70자 이내): 검색 키워드 나열. 파이프(|)로 구분. 소문자 영어+한국어 혼용

예시:
{{"line1": "도쿄의 밤거리를 혼자 걷는 그 느낌. 1시간 루프.", "line2": "city pop bgm | 시티팝 | lofi | 공부 음악 | 드라이브 bgm | 작업 음악 | 수면 bgm"}}

JSON만. 다른 텍스트 없이."""


# ── YouTube 인증 (uploader.py 동일 방식: token.pickle) ───────────────────
def get_youtube_client():
    creds      = None
    token_path = BASE_DIR / "token.pickle"
    secret_path = os.getenv(
        "YOUTUBE_CLIENT_SECRET_FILE",
        str(BASE_DIR / "client_secret.json")
    )

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(secret_path, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


# ── 영상 목록 수집 ────────────────────────────────────────────────────────
def fetch_all_videos(youtube, scheduled_only=False):
    print("📡 채널 정보 가져오는 중...")
    ch = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    videos, next_token = [], None
    print("📋 영상 목록 수집 중...")
    while True:
        pl = youtube.playlistItems().list(
            part="snippet,status", playlistId=uploads_id,
            maxResults=50, pageToken=next_token
        ).execute()
        for item in pl["items"]:
            sn   = item["snippet"]
            priv = item.get("status", {}).get("privacyStatus", "public")
            videos.append({
                "video_id":       sn["resourceId"]["videoId"],
                "original_title": sn["title"],
                "url":            f"https://youtu.be/{sn['resourceId']['videoId']}",
                "status":         priv,
                "is_scheduled":   priv in ("private", "unlisted"),
                "published_at":   sn.get("publishedAt", ""),
            })
        next_token = pl.get("nextPageToken")
        if not next_token:
            break
        time.sleep(0.3)

    if scheduled_only:
        videos = [v for v in videos if v["is_scheduled"]]
        print(f"✅ 예약 영상 {len(videos)}개")
    else:
        ns = sum(1 for v in videos if v["is_scheduled"])
        print(f"✅ 전체 {len(videos)}개 (예약 {ns} / 공개 {len(videos)-ns})")
    return videos


def fetch_video_details(youtube, video_ids):
    details = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        resp  = youtube.videos().list(
            part="snippet,statistics", id=",".join(chunk)
        ).execute()
        for item in resp["items"]:
            details[item["id"]] = item
        time.sleep(0.2)
    return details


# ── 채널 분석 ────────────────────────────────────────────────────────────
def run_analyze(youtube):
    videos  = fetch_all_videos(youtube)
    details = fetch_video_details(youtube, [v["video_id"] for v in videos])
    rows = []
    for v in videos:
        stats = details.get(v["video_id"], {}).get("statistics", {})
        rows.append({
            "title":    v["original_title"][:52],
            "views":    int(stats.get("viewCount", 0)),
            "is_sched": v["is_scheduled"],
        })
    rows.sort(key=lambda x: x["views"], reverse=True)
    print("\n" + "=" * 65)
    print("📊 채널 영상 성과 분석 (상위 15개)")
    print("=" * 65)
    for i, r in enumerate(rows[:15], 1):
        tag  = "🏆" if i == 1 else f"{i:2d} "
        stag = "🔒" if r["is_sched"] else "🌐"
        print(f" {tag} {stag} {r['views']:4d}회  {r['title']}")
    ns   = sum(1 for r in rows if r["is_sched"])
    nz   = sum(1 for r in rows if r["views"] == 0)
    print(f"\n  전체 {len(rows)}개 | 예약 {ns}개 | 0회 {nz}개 | 최고 {rows[0]['views']}회")
    print(f"  권장: python seo_title_updater.py --preview --scheduled")


# ── Claude SEO 생성 ───────────────────────────────────────────────────────
def call_claude(client, prompt, max_tokens=200):
    """Claude API 호출. 모델: claude-sonnet-4-6"""
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return msg.content[0].text.strip()


def clean_title(raw: str) -> str:
    """마크다운 펜스·따옴표 제거 후 첫 줄만 반환"""
    raw = re.sub(r"^```[^\n]*\n?", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"```$", "", raw, flags=re.MULTILINE)
    raw = raw.strip().strip('"\'')
    return raw.split("\n")[0].strip()


def validate_title(title: str) -> bool:
    """[Playlist] 로 시작하는지 확인"""
    return title.startswith("[Playlist]")


def generate_seo_for_video(client, original_title: str, orig_desc: str) -> dict:
    # ── 제목 생성 (최대 2회 재시도) ──
    prompt = SEO_TITLE_PROMPT.format(original_title=original_title)
    new_title = ""
    for attempt in range(3):
        raw       = call_claude(client, prompt, max_tokens=150)
        new_title = clean_title(raw)
        if validate_title(new_title):
            break
        if attempt < 2:
            prompt += f"\n\n주의: 반드시 [Playlist] 로 시작해야 합니다. 다시 생성하세요."
            time.sleep(0.5)
    else:
        # 3회 시도 후에도 포맷 미준수 → 수동으로 [Playlist] 붙이기
        if new_title and not validate_title(new_title):
            new_title = "[Playlist] 🎧 " + new_title.lstrip("🎧🌙☕🌆🚗🌸 ")

    # ── 설명 첫 2줄 생성 ──
    desc_prompt = SEO_DESC_PROMPT.format(
        new_title=new_title, original_title=original_title
    )
    raw_desc = call_claude(client, desc_prompt, max_tokens=200)
    raw_desc = re.sub(r"^```[^\n]*\n?|```$", "", raw_desc, flags=re.MULTILINE).strip()
    try:
        dj        = json.loads(raw_desc)
        new_intro = f"{dj.get('line1','')}\n{dj.get('line2','')}"
    except json.JSONDecodeError:
        new_intro = ""

    # ── 기존 설명 본문(Timestamps 등) 보존 ──
    lines = orig_desc.split("\n")
    try:
        split_idx = next(i for i, l in enumerate(lines) if not l.strip())
    except StopIteration:
        split_idx = min(2, len(lines))
    body     = "\n".join(lines[split_idx:]).lstrip("\n")
    new_desc = f"{new_intro}\n\n{body}".strip() if new_intro else orig_desc

    return {"new_title": new_title, "new_desc": new_desc}


def generate_all(videos, details):
    if not ANTHROPIC_API_KEY:
        raise ValueError(
            "ANTHROPIC_API_KEY 없음.\n"
            "  set ANTHROPIC_API_KEY=sk-ant-xxxxx"
        )
    client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    results = []

    print(f"\n🤖 Claude SEO 최적화 중... ({len(videos)}개) 모델: claude-sonnet-4-6")
    print("-" * 65)

    for i, v in enumerate(videos, 1):
        orig      = v["original_title"]
        d         = details.get(v["video_id"], {})
        orig_desc = d.get("snippet", {}).get("description", "")
        tag       = "🔒" if v["is_scheduled"] else "🌐"
        print(f"[{i:2d}/{len(videos)}] {tag} {orig[:44]}...")

        try:
            seo       = generate_seo_for_video(client, orig, orig_desc)
            new_title = seo["new_title"]
            new_desc  = seo["new_desc"]
            ok = "✅" if validate_title(new_title) else "⚠️ "
            print(f"        {ok} → {new_title}")
        except Exception as e:
            print(f"        ❌ 오류: {type(e).__name__}: {e}")
            new_title = orig
            new_desc  = orig_desc

        results.append({
            "video_id":       v["video_id"],
            "url":            v["url"],
            "is_scheduled":   v["is_scheduled"],
            "status":         v["status"],
            "original_title": orig,
            "new_title":      new_title,
            "original_desc":  orig_desc,
            "new_desc":       new_desc,
            "new_tags":       BASE_TAGS,
            "title_changed":  orig != new_title,
            "desc_changed":   orig_desc != new_desc,
        })
        time.sleep(1.0)

    with open(PREVIEW_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    changed = sum(1 for r in results if r["title_changed"])
    bad     = sum(1 for r in results if r["title_changed"] and not validate_title(r["new_title"]))
    print(f"\n✅ {changed}개 변경 예정 (포맷 미준수: {bad}개) · {PREVIEW_FILE.name}")
    return results


# ── 미리보기 출력 ─────────────────────────────────────────────────────────
def print_preview(results):
    print("\n" + "=" * 65)
    print("📋 SEO 변경 미리보기")
    print("=" * 65)
    for i, r in enumerate(results, 1):
        if not r["title_changed"]:
            continue
        tag = "🔒예약" if r["is_scheduled"] else "🌐공개"
        ok  = "" if validate_title(r["new_title"]) else " ⚠️포맷오류"
        print(f"\n[{i:2d}] {tag}{ok}  {r['url']}")
        print(f"  전: {r['original_title']}")
        print(f"  후: {r['new_title']}")
        if r.get("desc_changed") and r.get("new_desc"):
            first = r["new_desc"].split("\n")[0]
            print(f"  설명: {first[:62]}")

    changed = [r for r in results if r["title_changed"]]
    ns = sum(1 for r in changed if r["is_scheduled"])
    np_ = sum(1 for r in changed if not r["is_scheduled"])
    print(f"\n총 {len(changed)}개 변경 예정 (예약 {ns}개 / 공개 {np_}개)")
    print(f"태그: {len(BASE_TAGS)}개 키워드 전 영상 공통 적용")


# ── 백업 ─────────────────────────────────────────────────────────────────
def backup(videos, details):
    data = {}
    for v in videos:
        d = details.get(v["video_id"], {})
        sn = d.get("snippet", {})
        data[v["video_id"]] = {
            "title": v["original_title"],
            "desc":  sn.get("description", ""),
            "tags":  sn.get("tags", []),
        }
    with open(BACKUP_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"💾 백업: {BACKUP_FILE.name}")


# ── YouTube 적용 ──────────────────────────────────────────────────────────
def apply_updates(youtube, results, limit=None):
    to_update = [r for r in results if r["title_changed"]]
    if limit:
        to_update = to_update[:limit]
        print(f"\n⚡ 테스트 모드: {limit}개만 적용")

    print(f"\n🚀 YouTube 업데이트 ({len(to_update)}개) — 제목 + 설명 + 태그")
    print("-" * 65)
    success = failed = 0

    for i, r in enumerate(to_update, 1):
        vid = r["video_id"]
        print(f"[{i:2d}/{len(to_update)}] {r['new_title'][:52]}...")
        try:
            resp = youtube.videos().list(part="snippet", id=vid).execute()
            if not resp["items"]:
                print("  ⚠️  영상 없음")
                failed += 1
                continue
            snippet              = resp["items"][0]["snippet"]
            snippet["title"]     = r["new_title"]
            snippet["tags"]      = r.get("new_tags", BASE_TAGS)
            if r.get("desc_changed") and r.get("new_desc"):
                snippet["description"] = r["new_desc"]
            youtube.videos().update(
                part="snippet", body={"id": vid, "snippet": snippet}
            ).execute()
            print("  ✅")
            success += 1
        except Exception as e:
            print(f"  ❌ {type(e).__name__}: {e}")
            failed += 1
        time.sleep(1.2)

    print(f"\n결과: ✅ {success}개 성공 / ❌ {failed}개 실패")


# ── 복원 ─────────────────────────────────────────────────────────────────
def restore(youtube):
    if not BACKUP_FILE.exists():
        print(f"❌ 백업 파일 없음: {BACKUP_FILE}")
        return
    with open(BACKUP_FILE, encoding="utf-8") as f:
        data = json.load(f)
    print(f"♻️  {len(data)}개 복원 중...")
    for vid, info in data.items():
        try:
            resp = youtube.videos().list(part="snippet", id=vid).execute()
            if not resp["items"]:
                continue
            snippet                = resp["items"][0]["snippet"]
            snippet["title"]       = info["title"]
            snippet["description"] = info.get("desc", snippet["description"])
            snippet["tags"]        = info.get("tags", snippet.get("tags", []))
            youtube.videos().update(
                part="snippet", body={"id": vid, "snippet": snippet}
            ).execute()
            print(f"  ✅ {info['title'][:50]}")
        except Exception as e:
            print(f"  ❌ {vid}: {e}")
        time.sleep(1.2)
    print("✅ 복원 완료")


# ── 진입점 ───────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="J_Jlaylist SEO 일괄 수정 v2")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--analyze",   action="store_true")
    g.add_argument("--preview",   action="store_true")
    g.add_argument("--apply",     action="store_true")
    g.add_argument("--restore",   action="store_true")
    p.add_argument("--scheduled", action="store_true", help="예약 영상만")
    p.add_argument("--limit",     type=int, default=None)
    p.add_argument("--use-cache", action="store_true", help="seo_preview.json 재사용")
    args = p.parse_args()

    youtube = get_youtube_client()

    if args.restore:
        restore(youtube)
        return
    if args.analyze:
        run_analyze(youtube)
        return

    if args.use_cache and PREVIEW_FILE.exists():
        print(f"📂 캐시 사용: {PREVIEW_FILE.name}")
        with open(PREVIEW_FILE, encoding="utf-8") as f:
            results = json.load(f)
    else:
        videos  = fetch_all_videos(youtube, scheduled_only=args.scheduled)
        details = fetch_video_details(youtube, [v["video_id"] for v in videos])
        backup(videos, details)
        results = generate_all(videos, details)

    if args.preview:
        print_preview(results)
        return

    if args.apply:
        print_preview(results)
        scope = "예약 영상" if args.scheduled else "전체 영상"
        print(f"\n⚠️  {scope}에 제목 + 설명 + 태그 적용합니다.")
        if input("계속? (yes): ").strip().lower() != "yes":
            print("취소")
            return
        apply_updates(youtube, results, limit=args.limit)


if __name__ == "__main__":
    main()