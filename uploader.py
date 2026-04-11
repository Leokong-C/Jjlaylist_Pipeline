"""
uploader.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
YouTube 업로드 + 믹스 메타데이터 Claude API 자동 생성
"""

import os, json, pickle, re
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from dotenv import load_dotenv
from config import TOKEN_PATH                                   # ← 추가

load_dotenv()

SCOPES      = ["https://www.googleapis.com/auth/youtube"]
TOKEN_FILE  = TOKEN_PATH                                        # ← 수정
SECRET_FILE = os.getenv("YOUTUBE_CLIENT_SECRET_FILE",
                        str(Path(__file__).parent / "client_secret.json"))


def get_youtube_client():
    """
    token.pickle 로드 → 스코프 불일치 시 자동 재인증
    """
    creds = None

    if TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    # 스코프 불일치 감지 → 재인증
    if creds and hasattr(creds, "scopes") and creds.scopes:
        if not all(s in creds.scopes for s in SCOPES):
            print("  🔄 토큰 스코프 불일치 → 재인증 진행")
            creds = None

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


# ── 믹스 메타데이터 Claude API 자동 생성 ─────────────────────────────────
def generate_mix_metadata(mix_result: dict) -> dict:
    """
    mixer.py 결과 dict → YouTube 제목·설명·태그 자동 생성
    필요 환경변수: ANTHROPIC_API_KEY
    """
    import anthropic

    mood      = mix_result.get("mood", "all")
    label     = mix_result.get("label", "JAPANESE CITY POP MIX")
    emoji     = mix_result.get("emoji", "🎧")
    idx       = mix_result.get("mix_index", 1)
    ts        = mix_result.get("timestamps", "")
    dur       = mix_result.get("duration_min", 55)
    n_songs   = len(mix_result.get("songs", []))

    mood_ko = {
        "night":      "밤 드라이브·도시 네온",
        "cafe":       "카페·비·창가",
        "melancholy": "이별·추억·혼자",
        "dawn":       "새벽·여명",
        "all":        "시티팝·로파이 감성",
    }.get(mood, "시티팝")

    prompt = f"""\
너는 J_Jlaylist 유튜브 채널 SEO 전문가야.
채널: 일본 시티팝/Lofi AI 음악, 믹스 플레이리스트.

믹스 정보:
  테마: {mood_ko}
  곡 수: {n_songs}곡
  길이: {dur:.0f}분
  번호: #{idx:02d}

트랙리스트:
{ts}

아래 JSON만 출력 (마크다운·백틱 없이):
{{"title": "[Playlist] {emoji} {{감성표현 15~25자}} | {label} #{idx:02d} #Citypop", "description": "{{감성 첫 줄 40자}}\\n{{검색 키워드 줄}}\\n\\n{ts}\\n\\n🎧 J_Jlaylist — Japanese City Pop & Lofi Mix\\nAI Music by SUNO\\n\\n#citypop #시티팝 #lofi #japancitypop #playlist #공부음악 #드라이브bgm", "tags": ["citypop", "시티팝", "lofi", "japanese city pop", "일본 시티팝", "playlist", "tokyo", "도쿄", "공부 음악", "드라이브 bgm", "작업 음악", "city pop bgm", "j_jlaylist", "ai music"]}}

title 규칙:
- 반드시 [Playlist] {emoji} 로 시작
- 경험·감성 표현 15~25자: "퇴근길 도시 불빛이 물처럼 번지는" 스타일
- 끝: | {label} #{idx:02d} #Citypop"""

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY 환경변수 없음\n"
                         "  set ANTHROPIC_API_KEY=sk-ant-xxxxx")

    client = anthropic.Anthropic(api_key=api_key)
    msg    = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=700,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = msg.content[0].text.strip()
    raw = re.sub(r"^```json\n?|^```\n?|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        meta = json.loads(raw)
    except json.JSONDecodeError:
        meta = {
            "title":       f"[Playlist] {emoji} 도쿄의 밤을 담은 시티팝 | {label} #{idx:02d} #Citypop",
            "description": f"Japanese City Pop Mix\n\n{ts}\n\n#citypop #시티팝 #lofi",
            "tags":        ["citypop", "시티팝", "lofi", "japanese city pop", "j_jlaylist"],
        }

    # title_ko 정규화 (업로드 함수가 title_ko 키를 사용)
    meta.setdefault("title_ko", meta.get("title", ""))
    return meta


def upload_video(video_path: str, metadata: dict,
                 thumbnail_path: str = None,
                 publish_at: str = None) -> str:
    """
    영상 업로드 후 video_id 반환
    metadata 키: title_ko (또는 title), description, tags
    publish_at: ISO 8601 (None이면 즉시 공개)
    """
    youtube = get_youtube_client()
    status  = "public" if publish_at is None else "private"
    title   = metadata.get("title_ko") or metadata.get("title", "")

    body = {
        "snippet": {
            "title":           title,
            "description":     metadata.get("description", ""),
            "tags":            metadata.get("tags", []),
            "categoryId":      metadata.get("category", "10"),
            "defaultLanguage": "ko",
        },
        "status": {
            "privacyStatus":           status,
            "publishAt":               publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        video_path, mimetype="video/mp4",
        resumable=True, chunksize=50 * 1024 * 1024
    )

    print(f"업로드 중: {title[:60]}")
    request  = youtube.videos().insert(part="snippet,status",
                                       body=body, media_body=media)
    response = None
    while response is None:
        status_obj, response = request.next_chunk()
        if status_obj:
            print(f"  {int(status_obj.progress() * 100)}%", end="\r")

    video_id = response["id"]
    print(f"\n✅ https://youtube.com/watch?v={video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(thumbnail_path)
        ).execute()
        print("  🖼  썸네일 완료")

    return video_id


def schedule_uploads(video_metadata_pairs: list, start_hour: int = 9):
    """
    여러 영상 예약 업로드
    pairs: [(video_path, metadata_dict, thumbnail_path), ...]
    """
    from datetime import datetime, timedelta, timezone
    kst       = timezone(timedelta(hours=9))
    base_time = datetime.now(kst).replace(hour=start_hour, minute=0,
                                          second=0, microsecond=0)
    results = []
    for i, (vp, meta, thumb) in enumerate(video_metadata_pairs):
        publish_str = (base_time + timedelta(days=i + 1)).isoformat()
        vid_id      = upload_video(vp, meta, thumb, publish_str)
        results.append({"video_id": vid_id, "publish_at": publish_str,
                        "title":    meta.get("title_ko") or meta.get("title")})
    return results