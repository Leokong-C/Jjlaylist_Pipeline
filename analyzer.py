"""
analyzer.py  ·  J_Jlaylist Weekly Analyzer  ·  v1
─────────────────────────────────────────────────────────────────
주간 채널 분석 자동화 시스템

기능:
  1. YouTube Analytics API로 7일 데이터 수집
  2. Claude API로 패턴 분석 + 개선안 자동 생성
  3. HTML 보고서 생성
  4. GitHub Issue 자동 생성 (개선안별 1건)
  5. Email 보고서 발송 준비

사용법:
  로컬:
    python analyzer.py --dry-run     # 분석만 (Issue 생성 X)
    python analyzer.py --apply        # 풀 실행 (Issue 생성 + 보고서 발송)
    python analyzer.py --days 14      # 분석 기간 변경 (기본 7일)

  자동화 (GitHub Actions):
    python analyzer.py --apply --auto
"""

import os
import sys
import io
import json
import time
import pickle
import base64
import argparse
from pathlib import Path
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import anthropic
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Windows CMD UTF-8 강제
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# ── 경로 ──────────────────────────────────────────────────────────
BASE_DIR        = Path(__file__).parent
TOKEN_FILE      = BASE_DIR / "token.pickle"
API_KEY_FILE    = BASE_DIR / "claude_api_key.txt"
REPORT_DIR      = BASE_DIR / "weekly_reports"
HISTORY_FILE    = BASE_DIR / "analyzer_history.json"
REPORT_DIR.mkdir(parents=True, exist_ok=True)

# ── 채널 정보 ────────────────────────────────────────────────────
CHANNEL_ID    = "UCYuOzLTEVZX7frX-jqlmeMA"
CHANNEL_TITLE = "J_Jlaylist"

# ── 인증 ─────────────────────────────────────────────────────────
def get_credentials():
    env_token = os.environ.get("TOKEN_PICKLE_B64")
    if env_token:
        creds = pickle.loads(base64.b64decode(env_token))
    elif TOKEN_FILE.exists():
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)
    else:
        sys.exit("❌ token.pickle 없음")

    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        if not env_token and TOKEN_FILE.exists():
            with open(TOKEN_FILE, "wb") as f:
                pickle.dump(creds, f)
    return creds


def get_youtube_data(creds):
    return build("youtube", "v3", credentials=creds)


def get_youtube_analytics(creds):
    return build("youtubeAnalytics", "v2", credentials=creds)


def get_claude_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key and API_KEY_FILE.exists():
        api_key = API_KEY_FILE.read_text(encoding="utf-8").strip()
    if not api_key:
        sys.exit("❌ ANTHROPIC_API_KEY 없음 (env or claude_api_key.txt)")
    return anthropic.Anthropic(api_key=api_key)


# ── 데이터 수집 ──────────────────────────────────────────────────
def collect_analytics(yt_analytics, days=7):
    """YouTube Analytics API로 7일 데이터 수집"""
    end_date = datetime.now(timezone.utc).date()
    start_date = end_date - timedelta(days=days)
    prev_start = start_date - timedelta(days=days)

    data = {
        "period": f"{start_date} ~ {end_date}",
        "prev_period": f"{prev_start} ~ {start_date}",
        "days": days,
    }

    # 1. 채널 전체 KPI (현재 기간)
    try:
        r = yt_analytics.reports().query(
            ids=f"channel=={CHANNEL_ID}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
        ).execute()
        if r.get("rows"):
            row = r["rows"][0]
            cols = [c["name"] for c in r["columnHeaders"]]
            data["current_kpi"] = dict(zip(cols, row))
    except Exception as e:
        print(f"⚠️ 현재 KPI 수집 실패: {e}")
        data["current_kpi"] = {}

    # 2. 채널 전체 KPI (이전 기간 비교용)
    try:
        r = yt_analytics.reports().query(
            ids=f"channel=={CHANNEL_ID}",
            startDate=str(prev_start),
            endDate=str(start_date),
            metrics="views,estimatedMinutesWatched,averageViewDuration,subscribersGained,subscribersLost",
        ).execute()
        if r.get("rows"):
            row = r["rows"][0]
            cols = [c["name"] for c in r["columnHeaders"]]
            data["previous_kpi"] = dict(zip(cols, row))
    except Exception as e:
        print(f"⚠️ 이전 KPI 수집 실패: {e}")
        data["previous_kpi"] = {}

    # 3. 영상별 성과 (상위 20개)
    try:
        r = yt_analytics.reports().query(
            ids=f"channel=={CHANNEL_ID}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="views,estimatedMinutesWatched,averageViewDuration",
            dimensions="video",
            sort="-views",
            maxResults=20,
        ).execute()
        videos = []
        if r.get("rows"):
            cols = [c["name"] for c in r["columnHeaders"]]
            for row in r["rows"]:
                videos.append(dict(zip(cols, row)))
        data["top_videos"] = videos
    except Exception as e:
        print(f"⚠️ 영상별 성과 수집 실패: {e}")
        data["top_videos"] = []

    # 4. 트래픽 소스
    try:
        r = yt_analytics.reports().query(
            ids=f"channel=={CHANNEL_ID}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="views,estimatedMinutesWatched",
            dimensions="insightTrafficSourceType",
            sort="-views",
        ).execute()
        sources = []
        if r.get("rows"):
            cols = [c["name"] for c in r["columnHeaders"]]
            for row in r["rows"]:
                sources.append(dict(zip(cols, row)))
        data["traffic_sources"] = sources
    except Exception as e:
        print(f"⚠️ 트래픽 소스 수집 실패: {e}")
        data["traffic_sources"] = []

    # 5. 시청자 인구통계 (국가)
    try:
        r = yt_analytics.reports().query(
            ids=f"channel=={CHANNEL_ID}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="views,estimatedMinutesWatched",
            dimensions="country",
            sort="-views",
            maxResults=15,
        ).execute()
        countries = []
        if r.get("rows"):
            cols = [c["name"] for c in r["columnHeaders"]]
            for row in r["rows"]:
                countries.append(dict(zip(cols, row)))
        data["countries"] = countries
    except Exception as e:
        print(f"⚠️ 국가별 수집 실패: {e}")
        data["countries"] = []

    # 6. 디바이스 타입
    try:
        r = yt_analytics.reports().query(
            ids=f"channel=={CHANNEL_ID}",
            startDate=str(start_date),
            endDate=str(end_date),
            metrics="views,estimatedMinutesWatched",
            dimensions="deviceType",
            sort="-views",
        ).execute()
        devices = []
        if r.get("rows"):
            cols = [c["name"] for c in r["columnHeaders"]]
            for row in r["rows"]:
                devices.append(dict(zip(cols, row)))
        data["devices"] = devices
    except Exception as e:
        print(f"⚠️ 디바이스 수집 실패: {e}")
        data["devices"] = []

    return data


def enrich_video_titles(yt_data, analytics_data):
    """영상 ID → 제목 매핑"""
    video_ids = [v["video"] for v in analytics_data.get("top_videos", [])]
    if not video_ids:
        return analytics_data

    title_map = {}
    duration_map = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i+50]
        r = yt_data.videos().list(
            part="snippet,contentDetails",
            id=",".join(chunk),
        ).execute()
        for it in r.get("items", []):
            title_map[it["id"]] = it["snippet"]["title"]
            duration_map[it["id"]] = it["contentDetails"]["duration"]

    for v in analytics_data["top_videos"]:
        vid = v["video"]
        v["title"] = title_map.get(vid, "(제목 없음)")
        v["duration"] = duration_map.get(vid, "")
        # Shorts 판정
        d = v["duration"]
        import re
        m = re.match(r"PT(?:(\d+)M)?(?:(\d+)S)?", d)
        if m:
            mins = int(m.group(1) or 0)
            secs = int(m.group(2) or 0)
            v["is_shorts"] = (mins * 60 + secs) <= 60
        else:
            v["is_shorts"] = False

    return analytics_data


# ── Claude 분석 ──────────────────────────────────────────────────
ANALYSIS_PROMPT = """당신은 YouTube 채널 성장 분석 전문가입니다.
다음은 J_Jlaylist (AI 시티팝/Lofi 자동화 채널) 의 주간 데이터입니다.

[채널 컨텍스트]
- 목표: YPP 도달 (500구독자 + 3000시간)
- 현재 자동화: v3 썸네일 일일 6개 적용 중 (D-day +1 시점)
- 콘텐츠: 30~36분 시티팝 믹스 (롱폼) + 60초 Shorts
- 최근 이슈: 5월 v5.1 썸네일 변경으로 CTR 0.9% 까지 하락 → 6/7 v3 복원 시작
- 시청자 패턴: BGM 청취 (PC 49%, TV 11.5%)

[데이터 - 분석 기간: {period}]
{data_json}

[당신의 역할]
이 데이터를 보고 다음 4가지를 수행:

1. **핵심 트렌드 진단** (3~5줄)
   - KPI 변화의 의미 (단순 증감이 아닌 인사이트)
   - 이전 기간 대비 무엇이 좋아지고 나빠졌는지

2. **위험 신호** (있을 경우만, 0~2건)
   - 즉시 대응 필요한 이상 신호
   - 예: 특정 영상 갑작스러운 시청 감소, 이탈률 급증

3. **발견된 기회 3건** (우선순위순)
   각 기회마다:
   - 우선순위: P0 (긴급) / P1 (중요) / P2 (관찰)
   - 한 줄 제목 (예: "비 오는 밤 시리즈 노출 +180%")
   - 근거: 어떤 데이터에서 이 결론을 내렸는지 (구체적 수치 포함)
   - 제안 액션: 구체적이고 실행 가능한 행동
   - 예상 ROI: 정량적 추정 (예: 시청시간 +50h/주)
   - 실행 시간: 분/시간 단위
   - 자동화 가능 여부: Y/N

4. **다음 주 측정 권장 KPI** (1~2개)
   - 어떤 지표를 다음 주에 봐야 하는지

[출력 형식]
반드시 다음 JSON 형식으로만 출력:

```json
{{
  "trend_diagnosis": "...",
  "risk_signals": [
    {{"severity": "high|medium", "description": "..."}}
  ],
  "opportunities": [
    {{
      "priority": "P0|P1|P2",
      "title": "...",
      "evidence": "...",
      "action": "...",
      "estimated_roi": "...",
      "execution_time": "...",
      "automatable": "Y|N"
    }}
  ],
  "next_week_kpi_focus": ["...", "..."]
}}
```

JSON 외 어떤 텍스트도 출력하지 마세요. 백틱 fence 안에 JSON만."""


def run_claude_analysis(claude, analytics_data):
    """Claude API로 분석 + 개선안 생성"""
    # 데이터 크기 축소 (영상별 데이터 상위 10개만)
    compact_data = {
        "current_kpi": analytics_data.get("current_kpi"),
        "previous_kpi": analytics_data.get("previous_kpi"),
        "top_videos": analytics_data.get("top_videos", [])[:10],
        "traffic_sources": analytics_data.get("traffic_sources", [])[:5],
        "countries": analytics_data.get("countries", [])[:10],
        "devices": analytics_data.get("devices", []),
    }

    prompt = ANALYSIS_PROMPT.format(
        period=analytics_data.get("period", ""),
        data_json=json.dumps(compact_data, ensure_ascii=False, indent=2),
    )

    print("[Claude] 분석 시작...")
    resp = claude.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.content[0].text

    # JSON 추출
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]
    text = text.strip()

    try:
        result = json.loads(text)
        print(f"[Claude] 분석 완료. 기회 {len(result.get('opportunities', []))}건 발견.")
        return result
    except json.JSONDecodeError as e:
        print(f"❌ Claude 응답 JSON 파싱 실패: {e}")
        print(f"응답 원문:\n{text[:500]}")
        return {
            "trend_diagnosis": "분석 실패. 데이터 확인 필요.",
            "risk_signals": [],
            "opportunities": [],
            "next_week_kpi_focus": [],
            "raw_response": text,
        }


# ── 보고서 생성 ──────────────────────────────────────────────────
def format_pct_change(curr, prev):
    if not prev or prev == 0:
        return "N/A"
    pct = ((curr - prev) / prev) * 100
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"


def format_int(v):
    try:
        return f"{int(float(v)):,}"
    except:
        return str(v)


def generate_email_html(analytics_data, analysis, issue_urls=None):
    """이메일용 HTML 보고서 생성"""
    curr = analytics_data.get("current_kpi", {})
    prev = analytics_data.get("previous_kpi", {})

    views_chg = format_pct_change(
        float(curr.get("views", 0)),
        float(prev.get("views", 0)),
    )
    wt_chg = format_pct_change(
        float(curr.get("estimatedMinutesWatched", 0)),
        float(prev.get("estimatedMinutesWatched", 0)),
    )
    subs_net = int(float(curr.get("subscribersGained", 0))) - int(float(curr.get("subscribersLost", 0)))

    # 기회 카드
    opps_html = ""
    for i, opp in enumerate(analysis.get("opportunities", [])):
        prio = opp.get("priority", "P2")
        color = {"P0": "#d32f2f", "P1": "#f57c00", "P2": "#1976d2"}.get(prio, "#666")
        issue_link = ""
        if issue_urls and i < len(issue_urls):
            issue_link = f'<a href="{issue_urls[i]}" style="display:inline-block;padding:8px 16px;background:#0366d6;color:white;text-decoration:none;border-radius:4px;font-size:13px;">컨펌하러 가기 →</a>'

        opps_html += f"""
        <div style="border-left:4px solid {color};padding:16px;margin:12px 0;background:#fafafa;">
          <div style="font-size:11px;font-weight:bold;color:{color};">[{prio}]</div>
          <div style="font-size:16px;font-weight:bold;margin:4px 0 8px;">{opp.get('title','')}</div>
          <div style="font-size:13px;color:#444;margin:4px 0;"><b>근거:</b> {opp.get('evidence','')}</div>
          <div style="font-size:13px;color:#444;margin:4px 0;"><b>제안:</b> {opp.get('action','')}</div>
          <div style="font-size:13px;color:#444;margin:4px 0;"><b>예상 ROI:</b> {opp.get('estimated_roi','')}</div>
          <div style="font-size:12px;color:#666;margin:4px 0;">⏱ {opp.get('execution_time','')} · 자동화: {opp.get('automatable','N')}</div>
          <div style="margin-top:12px;">{issue_link}</div>
        </div>
        """

    # 위험 신호
    risks_html = ""
    if analysis.get("risk_signals"):
        risks_html = "<h3 style='color:#d32f2f;'>⚠️ 위험 신호</h3><ul>"
        for r in analysis["risk_signals"]:
            risks_html += f"<li><b>[{r.get('severity','medium')}]</b> {r.get('description','')}</li>"
        risks_html += "</ul>"
    else:
        risks_html = "<p style='color:#388e3c;'>⚠️ 위험 신호: <b>없음</b> (이번 주)</p>"

    # 국가
    countries_html = ""
    for c in (analytics_data.get("countries") or [])[:5]:
        countries_html += f"<tr><td>{c.get('country','')}</td><td style='text-align:right;'>{format_int(c.get('views',0))}</td></tr>"

    next_kpi = ", ".join(analysis.get("next_week_kpi_focus", []))

    html = f"""<!DOCTYPE html>
<html><body style="font-family:-apple-system,'Segoe UI',sans-serif;color:#333;max-width:680px;margin:0 auto;padding:20px;">

<h1 style="border-bottom:3px solid #0366d6;padding-bottom:8px;">
  📊 J_Jlaylist 주간 분석
</h1>
<div style="color:#666;font-size:14px;margin-bottom:24px;">
  기간: {analytics_data.get('period','')}
</div>

<h2>🎯 핵심 KPI</h2>
<table style="width:100%;border-collapse:collapse;">
  <tr style="background:#f5f5f5;">
    <th style="padding:8px;text-align:left;">지표</th>
    <th style="padding:8px;text-align:right;">현재</th>
    <th style="padding:8px;text-align:right;">변화</th>
  </tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;">조회수</td>
      <td style="padding:8px;text-align:right;border-bottom:1px solid #eee;">{format_int(curr.get('views',0))}</td>
      <td style="padding:8px;text-align:right;border-bottom:1px solid #eee;color:{'#388e3c' if '+' in views_chg else '#d32f2f'}">{views_chg}</td></tr>
  <tr><td style="padding:8px;border-bottom:1px solid #eee;">시청시간(분)</td>
      <td style="padding:8px;text-align:right;border-bottom:1px solid #eee;">{format_int(curr.get('estimatedMinutesWatched',0))}</td>
      <td style="padding:8px;text-align:right;border-bottom:1px solid #eee;color:{'#388e3c' if '+' in wt_chg else '#d32f2f'}">{wt_chg}</td></tr>
  <tr><td style="padding:8px;">구독자 순증</td>
      <td style="padding:8px;text-align:right;">+{subs_net}</td>
      <td style="padding:8px;text-align:right;">-</td></tr>
</table>

<h2 style="margin-top:32px;">📈 트렌드 진단</h2>
<div style="background:#f0f7ff;padding:16px;border-radius:6px;line-height:1.6;">
  {analysis.get('trend_diagnosis','분석 데이터 없음')}
</div>

<h2 style="margin-top:32px;">🔥 발견된 기회 {len(analysis.get('opportunities', []))}건</h2>
<div style="color:#666;font-size:13px;margin-bottom:8px;">CEO 컨펌 필요 — 각 안건의 GitHub Issue에서 승인/거부/수정</div>
{opps_html}

{risks_html}

<h2 style="margin-top:32px;">🌏 시청자 분포 (상위 5개국)</h2>
<table style="width:100%;border-collapse:collapse;font-size:13px;">
  <tr style="background:#f5f5f5;"><th style="padding:8px;text-align:left;">국가</th><th style="padding:8px;text-align:right;">조회수</th></tr>
  {countries_html}
</table>

<h2 style="margin-top:32px;">📅 다음 주 측정 권장</h2>
<div style="background:#fffde7;padding:12px;border-radius:6px;">
  {next_kpi or '특이 사항 없음'}
</div>

<div style="margin-top:32px;padding-top:16px;border-top:1px solid #eee;color:#999;font-size:12px;text-align:center;">
  J_Jlaylist Weekly Analyzer v1 · 다음 보고: 일주일 후 일요일 09:00 KST<br>
  전체 데이터는 첨부 JSON 또는 GitHub Actions 페이지에서 확인 가능
</div>

</body></html>"""
    return html


# ── GitHub Issue 자동 생성 ───────────────────────────────────────
def create_github_issues(opportunities, repo, gh_token, analytics_period):
    """각 기회별로 GitHub Issue 자동 생성"""
    if not gh_token or not repo:
        print("⚠️ GH_TOKEN 또는 REPO 없음 → Issue 자동 생성 스킵")
        return []

    import urllib.request
    issue_urls = []
    for opp in opportunities:
        title = f"[{opp.get('priority','P2')}] {opp.get('title','')}"
        body = f"""## 자동 분석으로 발견된 개선 기회

**기간**: {analytics_period}

### 우선순위
{opp.get('priority','P2')}

### 근거
{opp.get('evidence','')}

### 제안 액션
{opp.get('action','')}

### 예상 ROI
{opp.get('estimated_roi','')}

### 실행 시간
{opp.get('execution_time','')}

### 자동화 가능
{opp.get('automatable','N')}

---

**CEO 컨펌 방법**:
- ✅ 승인: 댓글에 `/approve` 입력
- ❌ 거부: 댓글에 `/reject [사유]` 입력
- ✏️ 수정: 댓글에 `/modify [수정 내용]` 입력

Generated by J_Jlaylist Weekly Analyzer
"""
        priority_label = opp.get('priority','P2').lower()
        labels = [f"priority:{priority_label}", "weekly-analysis", "needs-confirmation"]

        url = f"https://api.github.com/repos/{repo}/issues"
        data = json.dumps({"title": title, "body": body, "labels": labels}).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"token {gh_token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read())
                issue_urls.append(result["html_url"])
                print(f"  ✓ Issue #{result['number']} 생성: {title[:50]}")
        except Exception as e:
            print(f"  ✗ Issue 생성 실패: {e}")
            issue_urls.append("")
    return issue_urls


# ── 히스토리 ─────────────────────────────────────────────────────
def save_history(analytics_data, analysis, issue_urls):
    history = []
    if HISTORY_FILE.exists():
        try:
            history = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        except:
            history = []
    history.append({
        "run_at": datetime.now(timezone.utc).isoformat(),
        "period": analytics_data.get("period"),
        "current_kpi": analytics_data.get("current_kpi"),
        "previous_kpi": analytics_data.get("previous_kpi"),
        "opportunities_count": len(analysis.get("opportunities", [])),
        "issue_urls": issue_urls,
    })
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


# ── main ─────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="분석만 (Issue X)")
    ap.add_argument("--apply", action="store_true", help="풀 실행 (Issue 생성)")
    ap.add_argument("--days", type=int, default=7, help="분석 기간 (기본 7일)")
    ap.add_argument("--auto", action="store_true", help="자동화 모드")
    args = ap.parse_args()

    if not (args.dry_run or args.apply):
        ap.print_help()
        sys.exit(0)

    print(f"━━━ J_Jlaylist Weekly Analyzer ━━━")
    print(f"채널: {CHANNEL_TITLE} ({CHANNEL_ID})")
    print(f"기간: 최근 {args.days}일\n")

    creds = get_credentials()
    yt_data = get_youtube_data(creds)
    yt_analytics = get_youtube_analytics(creds)
    claude = get_claude_client()

    print("[1/4] YouTube Analytics 데이터 수집...")
    analytics_data = collect_analytics(yt_analytics, days=args.days)
    analytics_data = enrich_video_titles(yt_data, analytics_data)
    print(f"  ✓ KPI / 영상 {len(analytics_data.get('top_videos',[]))}개 / 국가 {len(analytics_data.get('countries',[]))}개")

    print("\n[2/4] Claude API 분석...")
    analysis = run_claude_analysis(claude, analytics_data)

    print("\n[3/4] GitHub Issue 자동 생성...")
    issue_urls = []
    if args.apply:
        repo = os.environ.get("GITHUB_REPOSITORY", "Leokong-C/Jjlaylist_Pipeline")
        gh_token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        issue_urls = create_github_issues(
            analysis.get("opportunities", []),
            repo, gh_token,
            analytics_data.get("period", "")
        )
    else:
        print("  (dry-run: Issue 생성 스킵)")

    print("\n[4/4] HTML 보고서 생성...")
    html = generate_email_html(analytics_data, analysis, issue_urls)
    report_date = datetime.now(timezone.utc).date()
    report_file = REPORT_DIR / f"weekly_report_{report_date}.html"
    report_file.write_text(html, encoding="utf-8")
    print(f"  ✓ {report_file}")

    # 분석 결과 JSON도 저장 (이메일 첨부용)
    summary_file = REPORT_DIR / f"weekly_summary_{report_date}.json"
    summary_file.write_text(json.dumps({
        "period": analytics_data.get("period"),
        "current_kpi": analytics_data.get("current_kpi"),
        "previous_kpi": analytics_data.get("previous_kpi"),
        "analysis": analysis,
        "issue_urls": issue_urls,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {summary_file}")

    # 히스토리
    save_history(analytics_data, analysis, issue_urls)

    print(f"\n━━━ 완료 ━━━")
    print(f"  발견된 기회: {len(analysis.get('opportunities', []))}건")
    print(f"  생성된 Issue: {len(issue_urls)}건")

    if args.auto:
        print("\n::REPORT_START::")
        print(json.dumps({
            "period": analytics_data.get("period"),
            "opportunities": len(analysis.get("opportunities", [])),
            "issues_created": len([u for u in issue_urls if u]),
            "report_file": str(report_file),
        }, ensure_ascii=False, indent=2))
        print("::REPORT_END::")
        print(f"::RESULT::SUCCESS::{len(analysis.get('opportunities', []))}")


if __name__ == "__main__":
    main()