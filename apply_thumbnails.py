"""
apply_thumbnails.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
batch_log.json의 모든 video_id에 썸네일 일괄 적용
배치 번호 기반 mood 순환으로 배경 이미지 다양화

사용법:
  python apply_thumbnails.py --preview   # 대상 + mood 확인
  python apply_thumbnails.py             # 전체 적용
  python apply_thumbnails.py --batch 1   # 특정 배치만
"""

import json, time, argparse, pickle
from pathlib import Path
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from thumbnail_auto import generate_thumbnail, mood_for_batch

BASE_DIR  = Path(__file__).parent
BATCH_LOG = BASE_DIR / "batch_log.json"
SCOPES    = ["https://www.googleapis.com/auth/youtube"]

# 배치 번호 → 배경/텍스트 매핑 (미리보기용)
MOOD_DESC = {
    "night_drive":    "차량내부  | TOKYO NIGHT DRIVE",
    "cafe_rain":      "소녀폰/커플 | CITY POP RAIN",
    "melancholy":     "소녀폰/우주인 | JAPANESE LOFI",
    "dawn_morning":   "우주인/차량내부 | DAWN CITY POP",
    "neon_city":      "소녀폰/차량내부 | URBAN CITY POP",
    "midnight_drive": "차량내부  | MIDNIGHT CITY POP",
}


def get_youtube_client():
    creds = None
    tp    = BASE_DIR / "token.pickle"
    sec   = str(BASE_DIR / "client_secret.json")
    if tp.exists():
        with open(tp, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(sec, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(tp, "wb") as f:
            pickle.dump(creds, f)
    return build("youtube", "v3", credentials=creds)


def upload_thumb(youtube, video_id: str, img_path: Path) -> bool:
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(img_path), mimetype="image/jpeg")
        ).execute()
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preview", action="store_true", help="목록 + mood 확인")
    p.add_argument("--batch",   type=int, default=None, help="특정 배치 번호만")
    args = p.parse_args()

    with open(BATCH_LOG, encoding="utf-8") as f:
        log = json.load(f)

    targets = [e for e in log if e.get("video_id")]
    if args.batch:
        targets = [e for e in targets if e["batch"] == args.batch]

    print(f"\n썸네일 적용 대상: {len(targets)}개")
    print(f"{'배치':^6} {'video_id':^15} {'mood':^16} {'배경/텍스트'}")
    print("-" * 70)
    for e in targets:
        bn   = e["batch"]
        mood = mood_for_batch(bn)
        desc = MOOD_DESC.get(mood, mood)
        print(f"  #{bn:02d}   {e['video_id']:^15} {mood:^16} {desc}")

    if args.preview or not targets:
        return

    youtube = get_youtube_client()
    ok = fail = 0

    for e in targets:
        vid       = e["video_id"]
        batch_num = e["batch"]
        mood      = mood_for_batch(batch_num)
        title     = e.get("title", f"JAPANESE CITY POP MIX #{batch_num:02d}")

        print(f"\n[#{batch_num:02d}] {vid} | mood: {mood}")
        print(f"  제목: {title[:50]}")

        try:
            img = generate_thumbnail(vid, title, force_mood=mood)
            print(f"  🖼  생성: {img.name}")

            if upload_thumb(youtube, vid, img):
                print(f"  ✅ 완료")
                ok += 1
            else:
                fail += 1
        except Exception as err:
            print(f"  ❌ {err}")
            fail += 1

        time.sleep(1.0)

    print(f"\n✅ {ok}개 완료 / ❌ {fail}개 실패")


if __name__ == "__main__":
    main()