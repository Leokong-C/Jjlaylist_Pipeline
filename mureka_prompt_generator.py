"""
mureka_prompt_generator.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
Claude API로 Mureka.ai 음악 프롬프트 자동 생성

사용법:
  python mureka_prompt_generator.py --theme CozySitcom --count 10
  python mureka_prompt_generator.py --theme RetroMystery --count 10
  python mureka_prompt_generator.py --theme all --count 5

생성 결과:
  idea/{theme}_prompts.md   → Mureka에 붙여넣을 프롬프트 모음
  idea/{theme}_notion.csv   → Notion 트래킹용 CSV
  idea/prompt_queue.json    → 파이프라인 자동 소비용 큐
"""

import os
import json
import argparse
import csv
from pathlib import Path
from datetime import datetime
import anthropic

from config import BASE_DIR, PROMPT_DIR, get_anthropic_key

# ── 테마 정의 ────────────────────────────────────────────────────────────
THEMES = {
    "CozySitcom": {
        "description": "따뜻하고 아늑한 시트콤 배경음악 스타일",
        "mood": "warm, cozy, lighthearted, nostalgic sitcom",
        "bpm_range": "90–110 BPM",
        "instruments": "acoustic guitar, light piano, soft bass, warm strings",
        "references": "Friends OST, 90s Japanese drama BGM",
    },
    "RetroMystery": {
        "description": "레트로 미스터리 분위기, 1970–80s 탐정물 스타일",
        "mood": "mysterious, suspenseful, retro, cinematic",
        "bpm_range": "100–120 BPM",
        "instruments": "electric piano, funky bass, muted trumpet, vibraphone",
        "references": "City Hunter OST, Lupin III, retro detective noir",
    },
    "NightDrive": {
        "description": "심야 드라이브, 도시 네온, 시티팝 핵심",
        "mood": "cool, urban, nocturnal, bittersweet",
        "bpm_range": "110–126 BPM",
        "instruments": "synth bass, rhodes, layered synths, sax, drum machine",
        "references": "Tatsuro Yamashita, Mariya Takeuchi, Anri",
    },
    "DawnMorning": {
        "description": "새벽 여명, 감성적이고 서정적인 분위기",
        "mood": "peaceful, melancholic, hopeful, cinematic dawn",
        "bpm_range": "80–100 BPM",
        "instruments": "acoustic piano, soft strings, light percussion, ambient pads",
        "references": "Nujabes, early morning lo-fi, Japanese acoustic pop",
    },
    "CafeRain": {
        "description": "비 오는 카페, 로파이 힙합 + 시티팝 크로스오버",
        "mood": "rainy, cozy, introspective, lo-fi",
        "bpm_range": "85–100 BPM",
        "instruments": "vinyl crackle, mellow piano, soft guitar, warm bass",
        "references": "Lo-fi hip hop, Cafe Music BGM channel",
    },
    "MoonlitMusicalFeline": {
        "description": "달빛 아래 고양이 테마, 몽환적이고 귀여운 시티팝",
        "mood": "whimsical, dreamy, playful, nocturnal",
        "bpm_range": "100–118 BPM",
        "instruments": "toy piano, xylophone, soft synth, walking bass",
        "references": "Yuki Saito, cute 80s J-pop, Studio Ghibli adjacent",
    },
}

# ── 마스터 프롬프트 (공통 스타일 기준) ──────────────────────────────────
MASTER_STYLE = """Japanese city pop / urban pop, early 2000s production,
stacked harmonies, choir pads, maj7/m9 chords,
smooth instrumental texture, radio-friendly mix"""


def generate_prompts(theme: str, count: int, client: anthropic.Anthropic) -> list[dict]:
    """Claude API로 Mureka 프롬프트 count개 생성"""

    theme_info = THEMES[theme]

    system_prompt = """You are an expert music prompt engineer for AI music generators like Mureka.ai and Suno.
Your prompts must be:
- Specific, evocative, and immediately usable
- In English only
- Optimized for Mureka.ai's style tag system
- Each prompt must be unique with distinct emotional nuance
- Format: concise comma-separated style tags + 1 sentence mood description

Respond ONLY with a JSON array. No preamble, no markdown fences. Example:
[
  {
    "title": "Midnight Neon Waltz",
    "style_tags": "japanese city pop, night drive, synth bass, 118bpm, maj7 chords, 1980s, nostalgic",
    "mood_desc": "A bittersweet cruise through rain-slicked city streets under neon signs",
    "lyrics_hint": "Themes of fleeting romance, city lights, late-night coffee"
  }
]"""

    user_prompt = f"""Generate {count} unique Mureka.ai music prompts for the theme: "{theme}"

Theme details:
- Description: {theme_info['description']}
- Core mood: {theme_info['mood']}
- BPM range: {theme_info['bpm_range']}
- Key instruments: {theme_info['instruments']}
- Style references: {theme_info['references']}

Master style base (always blend with):
{MASTER_STYLE}

Requirements:
- Each track must feel distinct (vary BPM, key instruments, emotional angle)
- Include specific BPM in style_tags
- Include chord quality hints (maj7, m9, dim, etc.)
- lyrics_hint should suggest Japanese city pop lyric themes in English
- Return exactly {count} items in the JSON array"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4000,
        messages=[{"role": "user", "content": user_prompt}],
        system=system_prompt,
    )

    raw = response.content[0].text.strip()
    # JSON 펜스 제거 (안전장치)
    raw = raw.replace("```json", "").replace("```", "").strip()
    prompts = json.loads(raw)
    return prompts


def save_markdown(theme: str, prompts: list[dict]) -> Path:
    """Mureka에 바로 붙여넣을 수 있는 MD 파일 생성"""
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    out = PROMPT_DIR / f"{theme}_prompts.md"

    lines = [
        f"# {theme} — Mureka Prompt Bundle",
        f"생성일: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"총 {len(prompts)}곡\n",
        "---\n",
    ]
    for i, p in enumerate(prompts, 1):
        lines += [
            f"## Track {i:02d}: {p['title']}",
            f"**Style Tags (Mureka에 입력):**",
            f"```",
            p["style_tags"],
            f"```",
            f"**Mood:** {p['mood_desc']}",
            f"**Lyrics Hint:** {p['lyrics_hint']}",
            "",
        ]

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"  📝 MD 저장: {out}")
    return out


def save_csv(theme: str, prompts: list[dict]) -> Path:
    """Notion 트래킹용 CSV"""
    PROMPT_DIR.mkdir(parents=True, exist_ok=True)
    out = PROMPT_DIR / f"{theme}_notion.csv"

    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "No", "Title", "Theme", "Style Tags", "Mood", "Lyrics Hint",
            "Status", "Mureka URL", "Downloaded", "Notes"
        ])
        writer.writeheader()
        for i, p in enumerate(prompts, 1):
            writer.writerow({
                "No":          i,
                "Title":       p["title"],
                "Theme":       theme,
                "Style Tags":  p["style_tags"],
                "Mood":        p["mood_desc"],
                "Lyrics Hint": p["lyrics_hint"],
                "Status":      "대기",
                "Mureka URL":  "",
                "Downloaded":  "N",
                "Notes":       "",
            })

    print(f"  📊 CSV 저장: {out}")
    return out


def update_prompt_queue(theme: str, prompts: list[dict]):
    """파이프라인이 소비할 prompt_queue.json 업데이트"""
    queue_file = PROMPT_DIR / "prompt_queue.json"
    queue = []
    if queue_file.exists():
        queue = json.loads(queue_file.read_text(encoding="utf-8"))

    for p in prompts:
        queue.append({
            "theme":      theme,
            "title":      p["title"],
            "style_tags": p["style_tags"],
            "mood_desc":  p["mood_desc"],
            "status":     "pending",   # pending → generated → mixed → uploaded
            "created_at": datetime.now().isoformat(),
        })

    queue_file.write_text(json.dumps(queue, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    print(f"  🗂  큐 업데이트: {len(queue)}개 총 대기 중")


def main():
    parser = argparse.ArgumentParser(description="Mureka 프롬프트 자동 생성")
    parser.add_argument("--theme", default="CozySitcom",
                        choices=list(THEMES.keys()) + ["all"],
                        help="생성할 테마")
    parser.add_argument("--count", type=int, default=10,
                        help="테마당 생성 수 (기본 10)")
    args = parser.parse_args()

    client = anthropic.Anthropic(api_key=get_anthropic_key())

    themes = list(THEMES.keys()) if args.theme == "all" else [args.theme]

    for theme in themes:
        print(f"\n🎵 [{theme}] 프롬프트 {args.count}개 생성 중...")
        try:
            prompts = generate_prompts(theme, args.count, client)
            save_markdown(theme, prompts)
            save_csv(theme, prompts)
            update_prompt_queue(theme, prompts)
            print(f"  ✅ {theme} 완료 — {len(prompts)}개")
        except Exception as e:
            print(f"  ❌ {theme} 실패: {e}")

    print(f"\n✅ 모든 프롬프트 생성 완료 → {PROMPT_DIR}")
    print("\n📋 다음 단계:")
    print("  1. idea/{theme}_prompts.md 열기")
    print("  2. Style Tags를 Mureka.ai에 붙여넣기")
    print("  3. 생성된 MP3를 music/ 폴더에 저장")
    print("  4. git add music/*.mp3 && git push → 파이프라인 자동 실행")


if __name__ == "__main__":
    main()