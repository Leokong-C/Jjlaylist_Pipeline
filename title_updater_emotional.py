"""
title_updater_emotional.py
---------------------------
업로드된 YouTube 영상 제목을 감성형으로 일괄 수정
Claude API로 감정 상황 기반 제목 생성 → YouTube Data API로 적용

현재 패턴: [Playlist] 🎧 새벽 열차 창문으로 네온이 스쳐간다 | City Pop Mix
개선 패턴: 새벽 2시에 듣는 일본 시티팝 🌙 | 잠 못 드는 밤 플레이리스트

사용법:
    python title_updater_emotional.py --dry-run     # 미리보기 (실제 수정 안 함)
    python title_updater_emotional.py               # 전체 수정
    python title_updater_emotional.py --limit 5     # 5개만 수정
"""

import os
import sys
import json
import pickle
import argparse
import time
import re
from pathlib import Path

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import anthropic

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).parent
TOKEN_PATH    = BASE_DIR / "token.pickle"
CLIENT_SECRET = BASE_DIR / "client_secret.json"
SCOPES        = ["https://www.googleapis.com/auth/youtube"]
TITLE_LOG     = BASE_DIR / "title_update_log.json"

# ── 감성 제목 템플릿 (Claude API 실패 시 폴백) ────────────────────────────────
EMOTIONAL_TEMPLATES = [
    "새벽 {hour}시에 듣는 일본 시티팝 🌙 | {mood} 플레이리스트",
    "{mood}한 밤, 도쿄의 네온 아래 🎵 | 일본 시티팝 믹스",
    "비 오는 날 창문 너머로 듣는 시티팝 🌧️ | {mood} 감성",
    "혼자인 밤에 어울리는 일본 시티팝 🎶 | {mood} 로파이 믹스",
    "도쿄 새벽 {hour}시, {mood}의 시티팝 🌃 | 감성 플레이리스트",
]

MOODS = ["잔잔한", "몽환적인", "감성적인", "나른한", "아련한", "포근한", "고요한"]
HOURS = ["1", "2", "3", "새벽", "깊은 밤"]

# ── YouTube 인증 ───────────────────────────────────────────────────────────────
def get_youtube():
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)

# ── 업로드된 영상 목록 가져오기 ────────────────────────────────────────────────
def get_my_videos(youtube, max_results: int = 50) -> list[dict]:
    # 1. 내 채널의 업로드 플레이리스트 ID 가져오기
    ch_resp = youtube.channels().list(
        part="contentDetails", mine=True
    ).execute()
    uploads_id = (ch_resp["items"][0]["contentDetails"]
                  ["relatedPlaylists"]["uploads"])

    # 2. 플레이리스트에서 영상 목록 가져오기
    videos, next_page = [], None
    while len(videos) < max_results:
        pl_resp = youtube.playlistItems().list(
            part="snippet",
            playlistId=uploads_id,
            maxResults=min(max_results - len(videos), 50),
            pageToken=next_page
        ).execute()

        for item in pl_resp.get("items", []):
            sn = item["snippet"]
            videos.append({
                "video_id":    sn["resourceId"]["videoId"],
                "title":       sn["title"],
                "description": sn.get("description", ""),
            })

        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    return videos

# ── 이미 수정된 영상 필터링 ───────────────────────────────────────────────────
def load_title_log() -> dict:
    if TITLE_LOG.exists():
        with open(TITLE_LOG, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_title_log(log: dict):
    with open(TITLE_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ── Claude API: 감성 제목 생성 ────────────────────────────────────────────────
def generate_emotional_title(original_title: str, description: str) -> str:
    client = anthropic.Anthropic()

    prompt = f"""YouTube 음악 플레이리스트 제목을 감성형으로 바꿔주세요.

원래 제목: {original_title}
영상 설명 (일부): {description[:200]}

규칙:
1. 시청자의 감정 상황을 제목 앞에 배치 (예: "새벽 2시에 듣는", "잠 못 드는 밤", "비 오는 날")
2. 일본 시티팝 / 로파이 장르 유지
3. 이모지 1~2개 포함
4. 50자 이내
5. "플레이리스트" 또는 "믹스" 로 마무리
6. 제목 텍스트만 출력 (설명 없음)

좋은 예시:
- 새벽 2시에 듣는 일본 시티팝 🌙 | 잠 못 드는 밤 플레이리스트
- 비 오는 도쿄, 창문 너머 시티팝 🌧️ | 감성 로파이 믹스
- 혼자인 밤에 어울리는 시티팝 🎵 | 아련한 일본 감성"""

    try:
        resp = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}]
        )
        title = resp.content[0].text.strip()
        title = title.replace("```", "").strip()
        # 100자 초과 방지
        if len(title) > 100:
            title = title[:97] + "..."
        return title
    except Exception as e:
        print(f"  [WARN] Claude API 실패: {e} → 템플릿 사용")
        import random
        tmpl = random.choice(EMOTIONAL_TEMPLATES)
        return tmpl.format(
            hour=random.choice(HOURS),
            mood=random.choice(MOODS)
        )

# ── YouTube 제목 수정 ──────────────────────────────────────────────────────────
def update_video_title(youtube, video_id: str, new_title: str, description: str) -> bool:
    try:
        youtube.videos().update(
            part="snippet",
            body={
                "id": video_id,
                "snippet": {
                    "title":      new_title,
                    "description": description,
                    "categoryId": "10",  # Music
                }
            }
        ).execute()
        return True
    except Exception as e:
        print(f"  [ERROR] 제목 수정 실패: {e}")
        return False

# ── 이미 감성형인지 확인 ──────────────────────────────────────────────────────
def is_already_emotional(title: str) -> bool:
    emotional_keywords = [
        "새벽", "밤에", "비 오는", "혼자", "잠 못", "아련",
        "몽환", "도쿄의 밤", "창문", "네온 아래"
    ]
    return any(kw in title for kw in emotional_keywords)

# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="YouTube 영상 제목 감성형 일괄 수정"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="실제 수정 없이 미리보기")
    parser.add_argument("--limit",   type=int, default=50,
                        help="수정할 최대 영상 수 (기본: 50)")
    parser.add_argument("--force",   action="store_true",
                        help="이미 감성형인 제목도 재생성")
    args = parser.parse_args()

    print("=" * 60)
    print("  title_updater_emotional.py  —  감성형 제목 일괄 수정")
    print("=" * 60)

    youtube  = get_youtube()
    log      = load_title_log()

    print(f"\n영상 목록 가져오는 중...")
    videos = get_my_videos(youtube, max_results=args.limit)
    print(f"총 {len(videos)}개 영상 확인\n")

    success, skip, fail = [], [], []

    for i, video in enumerate(videos):
        vid   = video["video_id"]
        title = video["title"]

        print(f"[{i+1}/{len(videos)}] {title[:50]}")

        # 이미 수정된 영상 스킵
        if vid in log and not args.force:
            print(f"  [SKIP] 이미 수정됨")
            skip.append(vid)
            continue

        # 이미 감성형이면 스킵
        if is_already_emotional(title) and not args.force:
            print(f"  [SKIP] 이미 감성형 제목")
            skip.append(vid)
            continue

        # 새 제목 생성
        print(f"  → Claude API 감성 제목 생성 중...")
        new_title = generate_emotional_title(title, video["description"])
        print(f"  ✨ {new_title}")

        if args.dry_run:
            print(f"  [DRY-RUN] 수정 건너뜀")
            success.append(vid)
            continue

        # 적용
        ok = update_video_title(youtube, vid, new_title, video["description"])
        if ok:
            print(f"  ✅ 적용 완료")
            log[vid] = {
                "original": title,
                "new":      new_title,
                "updated":  __import__("datetime").datetime.now().isoformat()
            }
            save_title_log(log)
            success.append(vid)
        else:
            fail.append(vid)

        # API 레이트리밋 방지
        if not args.dry_run:
            time.sleep(2)

    # ── 결과 요약 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  완료: {len(success)}개  /  스킵: {len(skip)}개  /  실패: {len(fail)}개")
    if not args.dry_run:
        print(f"  로그: title_update_log.json")
    print("=" * 60)
    print("\n  ✅ 다음 단계: thumbnail_auto.py 감성 문구 적용")

if __name__ == "__main__":
    main()