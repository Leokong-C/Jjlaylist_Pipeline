"""
blog_generator.py
------------------
batch_log.json의 YouTube 업로드 정보 → Claude API → 네이버 블로그 포스트 HTML 생성
네이버 Open API로 자동 포스팅 (또는 HTML 파일 저장 후 수동 복붙)

사용법:
    python blog_generator.py               # 전체 배치 처리
    python blog_generator.py --batch 3     # 배치 3번만
    python blog_generator.py --dry-run     # 네이버 API 호출 없이 HTML만 생성
    python blog_generator.py --output-dir ./blog_posts  # 저장 폴더 지정

네이버 API 설정 (환경변수):
    NAVER_CLIENT_ID     : 네이버 개발자센터 앱 Client ID
    NAVER_CLIENT_SECRET : 네이버 개발자센터 앱 Client Secret
    NAVER_ACCESS_TOKEN  : OAuth 2.0 액세스 토큰 (블로그 쓰기 권한)

포스트 구조:
    1. 유튜브 영상 임베드 (썸네일 클릭 → 유튜브 이동)
    2. 트랙리스트 (타임스탬프 포함)
    3. 장르/분위기 설명
    4. 해시태그 (SEO 최적화)
"""

import os
import json
import argparse
import sys
import re
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime

import anthropic

# ── 경로 설정 ──────────────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
BATCH_LOG    = BASE_DIR / "batch_log.json"
BLOG_DIR     = BASE_DIR / "output" / "blog_posts"

# ── 네이버 API 설정 ────────────────────────────────────────────────────────────
NAVER_BLOG_API = "https://openapi.naver.com/blog/post.json"

# ── 해시태그 (네이버 블로그 SEO) ───────────────────────────────────────────────
NAVER_TAGS = [
    "시티팝", "로파이", "일본감성", "AI음악", "플레이리스트",
    "공부할때듣는음악", "집중력음악", "감성음악", "시티팝플레이리스트",
    "lofi", "citypop", "일본시티팝", "잔잔한음악", "카페음악"
]

# ── batch_log 로드 ─────────────────────────────────────────────────────────────
def load_batch_log() -> dict:
    if not BATCH_LOG.exists():
        print(f"[ERROR] batch_log.json 없음: {BATCH_LOG}")
        sys.exit(1)
    with open(BATCH_LOG, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return {str(i): v for i, v in enumerate(data)}
    return data

# ── 배치 항목 필터 ────────────────────────────────────────────────────────────
def get_target_batches(log: dict, batch_num: int | None) -> list[tuple[str, dict]]:
    items = []
    for key, val in log.items():
        if batch_num is not None and str(batch_num) != key:
            continue
        # 유튜브 video_id가 있는 항목만
        if not val.get("video_id"):
            continue
        # 이미 블로그 포스팅된 항목 스킵
        if val.get("blog_posted") and not val.get("blog_failed"):
            continue
        items.append((key, val))
    return items

# ── Claude API: 블로그 포스트 HTML 생성 ───────────────────────────────────────
def generate_blog_html(batch_key: str, batch_data: dict) -> str:
    """
    Claude API로 네이버 블로그용 HTML 포스트 생성
    """
    client = anthropic.Anthropic()

    video_id   = batch_data.get("video_id", "")
    mix_title  = batch_data.get("mix_title", f"J_Jlaylist Mix #{batch_key}")
    track_list = batch_data.get("track_list", [])
    publish_at = batch_data.get("publish_at", "")
    description = batch_data.get("description", "")

    # 트랙리스트 문자열 생성
    if track_list:
        tracks_str = "\n".join(
            f"{i+1}. {t}" if isinstance(t, str) else f"{i+1}. {t.get('title', t)}"
            for i, t in enumerate(track_list)
        )
    else:
        tracks_str = "트랙 정보 없음"

    thumbnail_url = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
    youtube_url   = f"https://youtu.be/{video_id}"

    prompt = f"""네이버 블로그 포스트 HTML을 작성해주세요.

유튜브 영상 정보:
- 제목: {mix_title}
- 영상 ID: {video_id}
- 유튜브 URL: {youtube_url}
- 썸네일: {thumbnail_url}
- 트랙리스트:
{tracks_str}
- 영상 설명: {description[:300] if description else '일본 시티팝 / 로파이 AI 음악 믹스'}

작성 규칙:
1. 네이버 블로그에 바로 붙여넣기 가능한 HTML
2. 스타일은 인라인 CSS만 사용 (외부 CSS 없음)
3. 구조: 제목 → 썸네일 이미지(유튜브 링크) → 소개글(2-3문장) → 트랙리스트 → 마무리 문장
4. 썸네일 이미지는 클릭하면 유튜브로 이동하는 <a> 태그
5. 소개글은 감성적인 한국어, 100-150자
6. 트랙리스트는 <ol> 리스트
7. 마무리: "👉 유튜브에서 전체 감상하기" 링크 버튼
8. 배경색: #1a1a2e (다크), 텍스트: #e0e0e0, 강조: #c8a2c8
9. HTML 코드만 출력 (마크다운 없음, 설명 없음, 코드 펜스 없음)

반드시 HTML만 출력하세요."""

    try:
        response = client.messages.create(
            model="claude-opus-4-5",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        html = response.content[0].text.strip()

        # 마크다운 코드 펜스 제거
        html = re.sub(r"^```(?:html)?\s*", "", html, flags=re.MULTILINE)
        html = re.sub(r"```\s*$", "", html, flags=re.MULTILINE)
        html = html.strip()

        return html

    except Exception as e:
        print(f"  [ERROR] Claude API 실패: {e}")
        # 폴백 HTML
        return _fallback_html(mix_title, video_id, youtube_url, thumbnail_url, tracks_str)

# ── 폴백 HTML (API 실패 시) ───────────────────────────────────────────────────
def _fallback_html(title, video_id, yt_url, thumb_url, tracks_str) -> str:
    tracks_html = "".join(
        f"<li>{line.strip()}</li>"
        for line in tracks_str.split("\n") if line.strip()
    )
    return f"""<div style="background:#1a1a2e;padding:20px;color:#e0e0e0;font-family:sans-serif">
<h2 style="color:#c8a2c8">{title}</h2>
<a href="{yt_url}" target="_blank">
  <img src="{thumb_url}" style="width:100%;max-width:640px;border-radius:8px" alt="{title}">
</a>
<p style="margin:16px 0">일본 시티팝과 로파이 감성이 담긴 AI 음악 믹스 플레이리스트입니다. 🎵</p>
<h3 style="color:#c8a2c8">🎵 트랙리스트</h3>
<ol style="line-height:2">{tracks_html}</ol>
<p style="text-align:center;margin-top:20px">
  <a href="{yt_url}" target="_blank"
     style="background:#c8a2c8;color:#1a1a2e;padding:12px 24px;border-radius:24px;text-decoration:none;font-weight:bold">
    👉 유튜브에서 전체 감상하기
  </a>
</p>
</div>"""

# ── 포스트 제목 생성 ──────────────────────────────────────────────────────────
def make_blog_title(mix_title: str, batch_key: str) -> str:
    # "Batch 3 Mix" 같은 기계적 제목을 감성적으로 변환
    clean = (mix_title
             .replace("_shorts", "")
             .replace("_", " ")
             .strip())
    return f"🎵 {clean} | 일본 시티팝 로파이 AI 플레이리스트 #{batch_key}"

# ── 네이버 블로그 API 포스팅 ──────────────────────────────────────────────────
def post_to_naver_blog(title: str, content: str, tags: list[str]) -> bool:
    access_token = os.environ.get("NAVER_ACCESS_TOKEN", "")
    if not access_token:
        print("  [WARN] NAVER_ACCESS_TOKEN 환경변수 없음 → 네이버 API 건너뜀")
        return False

    tags_str = ",".join(tags[:10])  # 네이버 최대 10개

    data = urllib.parse.urlencode({
        "title":   title,
        "content": content,
        "tags":    tags_str,
    }).encode("utf-8")

    req = urllib.request.Request(NAVER_BLOG_API, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {access_token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"  [OK] 네이버 블로그 포스팅 성공: {result.get('logNo', 'N/A')}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"  [ERROR] 네이버 API HTTP {e.code}: {body[:200]}")
        return False
    except Exception as e:
        print(f"  [ERROR] 네이버 API 실패: {e}")
        return False

# ── HTML 파일 저장 ────────────────────────────────────────────────────────────
def save_html_file(batch_key: str, title: str, html: str, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_key  = re.sub(r"[^\w]", "_", batch_key)
    filename  = f"blog_batch{safe_key}_{timestamp}.html"
    out_path  = output_dir / filename

    # 네이버 복붙용 완성 HTML 래핑
    full_html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>{title}</title>
</head>
<body>
<!-- ★ 아래 내용을 네이버 블로그 에디터 HTML 모드에 붙여넣으세요 ★ -->
{html}
<!-- ★ 여기까지 ★ -->
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    return out_path

# ── batch_log 업데이트 ─────────────────────────────────────────────────────────
def update_batch_log_blog(log: dict, batch_key: str, html_path: Path, posted: bool):
    log[batch_key]["blog_html_path"] = str(html_path)
    log[batch_key]["blog_posted"]    = posted
    log[batch_key]["blog_generated"] = datetime.now().isoformat()
    if not posted:
        log[batch_key]["blog_failed"] = True

    with open(BATCH_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)

# ── 메인 ───────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="YouTube 믹스 배치 → 네이버 블로그 포스트 자동 생성"
    )
    parser.add_argument("--batch",      type=int,  default=None,
                        help="처리할 배치 번호 (미지정 시 전체)")
    parser.add_argument("--dry-run",    action="store_true",
                        help="HTML만 생성, 네이버 API 호출 안 함")
    parser.add_argument("--output-dir", type=str,  default=None,
                        help="HTML 저장 폴더 (기본: output/blog_posts/)")
    parser.add_argument("--no-claude",  action="store_true",
                        help="Claude API 없이 기본 템플릿 사용")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else BLOG_DIR

    print("=" * 60)
    print("  blog_generator.py  —  J_Jlaylist 네이버 블로그 자동 생성")
    print("=" * 60)

    log     = load_batch_log()
    targets = get_target_batches(log, args.batch)

    if not targets:
        print("[INFO] 처리할 배치 없음 (미포스팅 + video_id 있는 항목)")
        if args.batch is not None:
            print(f"       배치 {args.batch}을 확인해주세요.")
        sys.exit(0)

    print(f"\n처리 대상: {len(targets)}개 배치\n")

    success, fail = [], []

    for batch_key, batch_data in targets:
        mix_title = batch_data.get("mix_title", f"Mix #{batch_key}")
        print(f"[배치 {batch_key}] {mix_title}")

        # 1. HTML 생성
        if args.no_claude:
            video_id   = batch_data.get("video_id", "")
            yt_url     = f"https://youtu.be/{video_id}"
            thumb_url  = f"https://img.youtube.com/vi/{video_id}/maxresdefault.jpg"
            track_list = batch_data.get("track_list", [])
            tracks_str = "\n".join(
                f"{i+1}. {t}" if isinstance(t, str) else f"{i+1}. {t.get('title', t)}"
                for i, t in enumerate(track_list)
            )
            html = _fallback_html(mix_title, video_id, yt_url, thumb_url, tracks_str)
        else:
            print("  → Claude API HTML 생성 중...")
            html = generate_blog_html(batch_key, batch_data)

        # 2. HTML 파일 저장
        blog_title = make_blog_title(mix_title, batch_key)
        html_path  = save_html_file(batch_key, blog_title, html, output_dir)
        print(f"  ✓ HTML 저장: {html_path.name}")

        # 3. 네이버 API 포스팅
        posted = False
        if not args.dry_run:
            print("  → 네이버 블로그 포스팅 중...")
            posted = post_to_naver_blog(blog_title, html, NAVER_TAGS)
        else:
            print("  [DRY-RUN] 네이버 API 건너뜀")

        # 4. batch_log 업데이트
        update_batch_log_blog(log, batch_key, html_path, posted)

        if posted or args.dry_run:
            success.append(batch_key)
        else:
            fail.append(batch_key)

    # ── 결과 요약 ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print(f"  완료: {len(success)}개  /  실패: {len(fail)}개")
    print(f"  HTML 폴더: {output_dir}")

    if args.dry_run or not os.environ.get("NAVER_ACCESS_TOKEN"):
        print("\n  📋 수동 포스팅 방법:")
        print("   1. output/blog_posts/ 폴더의 HTML 파일 열기")
        print("   2. <!-- ★ 아래 내용 → ★ 여기까지 ★ --> 사이 코드 복사")
        print("   3. 네이버 블로그 → 글쓰기 → HTML 모드 → 붙여넣기")
        print("\n  🔑 자동 포스팅 설정:")
        print("   NAVER_ACCESS_TOKEN 환경변수 설정 후 재실행")
        print("   (네이버 개발자센터 → 내 애플리케이션 → Blog 권한)")

    print("=" * 60)

if __name__ == "__main__":
    main()