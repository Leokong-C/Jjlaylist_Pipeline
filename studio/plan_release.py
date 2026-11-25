"""
plan_release.py · STEP 1 — 세계관(bible.yaml) → 릴리스 기획 패키지
──────────────────────────────────────────────────────────────
Claude가 앨범 콘셉트, 문장형 곡 제목, 한국어 가사, Mureka 스타일 프롬프트,
커버 이미지 프롬프트를 만들고 검토용 시트를 생성합니다.

사용법:
  python plan_release.py --theme "첫 번째 실패에 대하여"
  python plan_release.py --theme "..." --tracks 3
  python plan_release.py --mock              # API 없이 구조 테스트

출력: releases/<slug>/plan.json, releases/<slug>/lyrics_sheet.md
"""
import argparse, json, re, datetime as dt
import yaml
from config import BIBLE_FILE, CLAUDE_MODEL, anthropic_key, release_dir

SCHEMA = """{
  "album_title": "한국어 앨범 제목",
  "album_title_en": "English title",
  "slug": "영문-소문자-하이픈",
  "concept": "앨범 소개문 3~4문장 (유튜브 설명란 첫 단락에 그대로 사용)",
  "cover_prompt": "커버 이미지 생성 프롬프트 (영어, 미드저니용)",
  "tracks": [
    {
      "no": 1,
      "title": "문장형 한국어 제목",
      "title_en": "English title",
      "role": "앨범 내 역할 (오프닝/타이틀/전환/클라이맥스/엔딩)",
      "bpm": 0,
      "style": "Mureka prompt용 영어 프롬프트, 600자 이내, 장르·악기·보컬 질감·BPM",
      "exclude": "피하고 싶은 요소 (쉼표 구분, 참고용)",
      "lyrics": "섹션 태그가 포함된 전체 한국어 가사",
      "hook_line": "쇼츠 자막으로 쓸 후렴 핵심 한 줄",
      "shorts_caption": "쇼츠 설명 1~2문장"
    }
  ]
}"""

def build_prompt(bible: dict, theme: str, n: int) -> str:
    return f"""너는 버추얼 인디밴드의 A&R 겸 작사가다. 아래 세계관 설정서를 엄격히 따르며
'{theme}'를 주제로 {n}곡짜리 릴리스를 기획하라.

[세계관 설정서]
{yaml.safe_dump(bible, allow_unicode=True, sort_keys=False)}

[규칙]
- 곡들은 하나의 서사로 이어져야 하며, 각 곡의 role이 겹치지 않게 한다.
- 가사는 한국어, 섹션 태그 사용, 곡당 2분 30초~3분 분량.
- style에는 보컬 성별/질감을 넣지 마라 (보컬은 본인 목소리 vocal_id로 고정).
- 가수·곡명 등 실존 아티스트 이름을 style에 넣지 마라.
- 반드시 아래 JSON 스키마로만 답하라. 다른 텍스트 금지.

{SCHEMA}"""

def call_claude(prompt: str) -> dict:
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key())
    msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=12000,
                                 messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in msg.content if b.type == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise SystemExit("JSON 파싱 실패:\n" + text[:500])
    return json.loads(m.group(0))

def mock_plan(theme: str, n: int) -> dict:
    return {"album_title": f"{theme}", "album_title_en": "Mock Album", "slug": "mock-album",
            "concept": "테스트용 앨범 소개입니다.", "cover_prompt": "dark lab window at dawn",
            "tracks": [{"no": i, "title": f"테스트 곡 {i}", "title_en": f"Test {i}", "role": "test",
                        "bpm": 90, "style": "korean indie rock, clean guitar", "exclude": "edm",
                        "lyrics": "[Verse]\n가사\n[Chorus]\n후렴", "hook_line": "후렴 한 줄",
                        "shorts_caption": "테스트"} for i in range(1, n + 1)]}

def write_sheet(plan: dict, bible: dict, out) -> None:
    lines = [f"# {plan['album_title']} ({plan['album_title_en']})", "",
             plan["concept"], "", f"**커버 프롬프트:** `{plan['cover_prompt']}`", "",
             "## 다음 단계", "1. 아래 가사·스타일을 검토하고 고칠 곳은 `plan.json`에서 직접 수정",
             f"2. `python generate_songs.py --slug {plan['slug']}`", ""]
    for t in plan["tracks"]:
        lines += ["---", f"## {t['no']:02d}. {t['title']}  ·  {t['role']}  ·  {t.get('bpm','')} BPM", "",
                  "**Title**", "```", t["title"], "```", "**Style**", "```", t["style"], "```",
                  "**Exclude**", "```", t.get("exclude", ""), "```", "**Lyrics**", "```", t["lyrics"], "```", ""]
    out.write_text("\n".join(lines), encoding="utf-8")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="첫 번째 릴리스")
    ap.add_argument("--tracks", type=int)
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    bible = yaml.safe_load(BIBLE_FILE.read_text(encoding="utf-8"))
    n = a.tracks or bible.get("release", {}).get("tracks_per_release", 5)
    plan = mock_plan(a.theme, n) if a.mock else call_claude(build_prompt(bible, a.theme, n))
    plan["slug"] = re.sub(r"[^a-z0-9-]", "", plan["slug"].lower()) or dt.date.today().isoformat()
    plan["created"] = dt.datetime.now().isoformat(timespec="seconds")
    d = release_dir(plan["slug"])
    (d / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    write_sheet(plan, bible, d / "lyrics_sheet.md")
    print(f"✅ 기획 완료 → {d}\n   검토 시트: {d/'lyrics_sheet.md'}")

if __name__ == "__main__":
    main()
