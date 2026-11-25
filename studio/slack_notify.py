"""
slack_notify.py · 업로드 승인 요청 / 결과를 Slack으로 푸시 (Incoming Webhook, 표준 라이브러리만 사용)

  python slack_notify.py request  pending.json <run_url>   # 승인 요청
  python slack_notify.py result   <RESULT> <run_url>        # 업로드 결과
환경변수: SLACK_WEBHOOK_URL
"""
import json, os, sys, urllib.request

def post(payload):
    url = os.getenv("SLACK_WEBHOOK_URL", "")
    if not url:
        print("⚠️ SLACK_WEBHOOK_URL 없음 — Slack 알림 생략"); print(json.dumps(payload, ensure_ascii=False)[:1500]); return
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()

def mmss(s): s = int(s or 0); return f"{s//60}:{s%60:02d}"

def request(pending_file, run_url):
    p = json.load(open(pending_file, encoding="utf-8"))
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": "🎧 J_Jlaylist 업로드 승인 요청"}}]
    for r in p["releases"]:
        if r["approved"]:
            continue
        lines = "\n".join(f"`{t['no']:02d}` *{t['title']}* ({mmss(t['dur'])}, take {t['take'] or '-'})\n      _“{t['hook']}”_"
                          for t in r["tracks"])
        blocks += [{"type": "section", "text": {"type": "mrkdwn", "text":
                    f"*{r['album']}*  (`{r['slug']}`)\n풀앨범 예약 공개: *{r['album_at']} KST* · 쇼츠 {len(r['tracks'])}개는 다음날부터 하루 1개"}},
                   {"type": "section", "text": {"type": "mrkdwn", "text": lines[:2900]}},
                   {"type": "divider"}]
    blocks += [{"type": "context", "elements": [{"type": "mrkdwn", "text":
                "모든 영상은 비공개+예약 공개, AI 합성 콘텐츠 표시. 미리보기 영상은 실행 페이지 하단 Artifacts에서 받을 수 있어요."}]},
               {"type": "actions", "elements": [
                   {"type": "button", "style": "primary", "text": {"type": "plain_text", "text": "검토 · 승인하기"}, "url": run_url},
                   {"type": "button", "text": {"type": "plain_text", "text": "미리보기 받기"}, "url": run_url + "#artifacts"}]}]
    post({"text": "J_Jlaylist 업로드 승인 요청", "blocks": blocks})

def result(res, run_url):
    icon = "✅" if res.startswith("UPLOADED") else ("⏭" if res == "NOTHING_TO_DO" else "❌")
    post({"text": f"{icon} J_Jlaylist 업로드 결과: {res}\n{run_url}"})

if __name__ == "__main__":
    {"request": request, "result": result}[sys.argv[1]](sys.argv[2], sys.argv[3])
