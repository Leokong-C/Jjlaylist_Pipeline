"""
retry_upload.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
batch_log.json에서 video_id: null인 배치만 골라서 재업로드
기존 예약 일정 뒤에 이어서 예약

사용법:
  python retry_upload.py --preview   # 재시도 대상 확인
  python retry_upload.py             # 실제 업로드
"""

import json, argparse
from pathlib import Path
from datetime import datetime, timedelta, timezone

from uploader import generate_mix_metadata, upload_video

BASE_DIR   = Path(__file__).parent
BATCH_LOG  = BASE_DIR / "batch_log.json"
KST        = timezone(timedelta(hours=9))
UPLOAD_HOUR     = 9
DAYS_INTERVAL   = 2


def load_log():
    with open(BATCH_LOG, encoding="utf-8") as f:
        return json.load(f)

def save_log(log):
    with open(BATCH_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


def next_publish_time(log: list) -> str:
    """기존 로그 중 가장 마지막 예약 시각 뒤에 이어서 계산"""
    now  = datetime.now(KST)
    # video_id 있는 것들 중 가장 늦은 publish_at
    valid = [l for l in log if l.get("video_id")]
    if valid:
        last = max(datetime.fromisoformat(l["publish_at"]) for l in valid)
        base = last + timedelta(days=DAYS_INTERVAL)
        if base <= now:
            base = now.replace(hour=UPLOAD_HOUR, minute=0,
                               second=0, microsecond=0) + timedelta(days=1)
    else:
        base = now.replace(hour=UPLOAD_HOUR, minute=0,
                           second=0, microsecond=0) + timedelta(days=1)
    return base.isoformat()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--preview", action="store_true")
    args = p.parse_args()

    log     = load_log()
    targets = [e for e in log if not e.get("video_id")]

    print(f"\n재업로드 대상: {len(targets)}개 배치")
    for e in targets:
        print(f"  배치 #{e['batch']:02d} | {Path(e['output']).name}")

    if not targets:
        print("✅ 재시도할 항목 없음. 모두 업로드 완료 상태입니다.")
        return

    if args.preview:
        # 새 예약 시각 미리보기
        preview_log = [l for l in log if l.get("video_id")]
        for e in targets:
            t = next_publish_time(preview_log)
            print(f"  배치 #{e['batch']:02d} → 새 예약 시각: {t[:16]}")
            preview_log.append({"publish_at": t, "video_id": "preview"})
        print(f"\n실행: python retry_upload.py")
        return

    confirm = input(f"\n{len(targets)}개 배치를 재업로드합니다. 계속? (yes): ").strip().lower()
    if confirm != "yes":
        print("취소")
        return

    for entry in targets:
        mp4_path = Path(entry["output"])
        if not mp4_path.exists():
            print(f"❌ 파일 없음: {mp4_path.name}")
            continue

        batch_num = entry["batch"]
        publish_at = next_publish_time(log)

        print(f"\n배치 #{batch_num:02d} | 예약: {publish_at[:16]}")
        print(f"  파일: {mp4_path.name}")

        # 메타데이터 재생성
        mix_result = {
            "mood":         "all",
            "mix_index":    batch_num,
            "label":        "JAPANESE CITY POP MIX",
            "emoji":        "🎧",
            "timestamps":   entry.get("ts", ""),
            "duration_min": 55,
            "songs":        entry.get("songs", []),
            "thumbnail":    None,
        }

        try:
            print("  🤖 메타데이터 생성 중...")
            meta  = generate_mix_metadata(mix_result)
            title = meta.get("title_ko") or meta.get("title", "")
            print(f"  제목: {title}")

            video_id = upload_video(
                video_path=str(mp4_path),
                metadata=meta,
                thumbnail_path=None,
                publish_at=publish_at,
            )

            # 로그 업데이트
            for e in log:
                if e["batch"] == batch_num:
                    e["video_id"]   = video_id
                    e["publish_at"] = publish_at
                    break
            save_log(log)
            print(f"  ✅ 완료 — video_id: {video_id}")

        except Exception as e:
            print(f"  ❌ 실패: {e}")

    print(f"\n✅ 재업로드 완료. batch_log.json 업데이트됨.")


if __name__ == "__main__":
    main()