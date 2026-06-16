import anthropic
import json
import os
from dotenv import load_dotenv

load_dotenv()
client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

SYSTEM_PROMPT = """당신은 YouTube Lofi/Citypop 채널 전문 SEO 최적화 전문가입니다.

[J_Jlaylist 채널 컨텍스트]
- 시청자 패턴: 데스크탑 49% + TV 11.5% (BGM 청취 집중)
- 핵심 타겟: PC로 작업/공부하면서 듣는 청자
- 글로벌 확장 중: 영문 키워드 비중 50% 유지

[필수 SEO 키워드 — description과 tags에 자연스럽게 포함]
한국어 작업/집중 키워드:
- "작업용 BGM", "집중용 BGM", "공부할 때 듣는 음악", "야근 BGM"
- "카페에서 작업", "새벽 작업", "재택근무 BGM", "코딩할 때 듣는 음악"

영문 작업/집중 키워드:
- "Study BGM", "Work BGM", "Focus Music", "Concentration Music"
- "Background Music for Work", "Productivity Music", "Coding Music"

[Description 작성 규칙]
1. 첫 문장은 반드시 청취 상황 명시:
   예시: "작업할 때 듣기 좋은 잔잔한 시티팝 플레이리스트"
        "Study and work with this Japanese citypop mix"
2. 한영 혼용 비중 50:50 유지 (글로벌 노출 확장)
3. 타임스탬프 + 해시태그 10개 포함

[Tags 작성 규칙]
- 총 15개 중 최소 4개는 작업/집중 키워드
- 한국어 5~7개 + 영문 7~10개
- 반드시 포함: "작업용 BGM", "집중용 BGM", "Study BGM", "Work BGM"

JSON 형식으로만 응답하세요. 마크다운 없이 순수 JSON만."""

def generate_metadata(
    track_mood: str,
    genre: str,  # "citypop" or "lofi"
    bpm: int = None,
    instruments: list = None,
    duration_hours: float = 1.0
) -> dict:
    """트랙 정보 → YouTube 메타데이터 자동 생성"""
    
    duration_str = f"{int(duration_hours)}시간" if duration_hours >= 1 else f"{int(duration_hours*60)}분"
    
    user_prompt = f"""
다음 트랙의 YouTube 업로드용 메타데이터를 생성해주세요:

장르: {genre}
무드/분위기: {track_mood}
BPM: {bpm or '알 수 없음'}
악기: {', '.join(instruments) if instruments else '미지정'}
영상 길이: {duration_str}

다음 JSON 형식으로 정확히 응답하세요:
{{
  "title_ko": "한국어 제목 (40자 이내, 이모지 포함)",
  "title_en": "English title (50 chars max)",
  "description": "한영 혼용 설명 (500자, 타임스탬프 포함, 해시태그 10개)",
  "tags": ["태그1", "태그2", ... 최대15개],
  "category": "10",
  "thumbnail_keyword": "썸네일 검색용 영어 키워드"
}}
"""
    
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[
            {"role": "user", "content": user_prompt}
        ],
        system=SYSTEM_PROMPT
    )
    
    raw = message.content[0].text
    raw = raw.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    if raw.startswith("```"):
        raw = raw[3:].strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"JSON 파싱 실패: {e}")
        print(f"응답 원문: {raw[:300]}")
        return None


def batch_generate(track_list: list) -> list:
    results = []
    for track in track_list:
        file_name = track.pop("file_name", "")
        success = False
        for attempt in range(3):  # 최대 3번 재시도
            try:
                meta = generate_metadata(**track)
                if meta is None:
                    continue
                meta["file_name"] = file_name
                results.append(meta)
                print(f"생성 완료: {meta['title_ko']}")
                success = True
                break
            except Exception as e:
                print(f"재시도 {attempt+1}/3: {file_name}")
                continue
        if not success:
            print(f"최종 건너뜀: {file_name}")
    return results


# 사용 예시
if __name__ == "__main__":
    from pathlib import Path
    import json

    music_files = list(Path("music/").glob("*.mp3"))
    tracks = []
    for f in music_files:
        parts = f.stem.split(".")
        name = parts[-1].strip() if len(parts) > 1 else f.stem
        genre = "citypop" if any(k in name.lower() for k in ["city", "tokyo", "neon", "midnight", "cassette"]) else "lofi"
        tracks.append({
            "file_name": f.name,
            "genre": genre,
            "track_mood": name,
            "duration_hours": 1.0
        })

    print(f"총 {len(tracks)}개 트랙 메타데이터 생성 시작...")
    metadata_list = batch_generate(tracks)

    with open("metadata_output.json", "w", encoding="utf-8") as f:
        json.dump(metadata_list, f, ensure_ascii=False, indent=2)

    print(f"완료! metadata_output.json 저장됨")
    
def generate_pond5_metadata(file_name: str, track_mood: str, genre: str) -> dict:
    """Pond5 스톡뮤직 등록용 영문 메타데이터 생성"""
    
    prompt = f"""
Generate Pond5 stock music metadata in English only.
Track info: genre={genre}, mood={track_mood}

Respond ONLY with this exact JSON, no other text:
{{
  "title": "English title (60 chars max, no emoji)",
  "description": "English description (200 chars, mention use cases like study, relax, background)",
  "keywords": ["keyword1", "keyword2", "keyword3", "keyword4", "keyword5", "keyword6", "keyword7", "keyword8", "keyword9", "keyword10"],
  "tempo": "slow",
  "mood": ["Calm", "Peaceful"],
  "genre": "Electronic",
  "instruments": ["Piano", "Synthesizer"]
}}
"""
    
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}],
        system="You are a stock music metadata expert. Respond only with valid JSON, no markdown, no explanation."
    )
    
    raw = message.content[0].text.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    
    result = json.loads(raw.strip())
    result["file_name"] = file_name
    return result


def batch_generate_pond5(track_list: list) -> list:
    """전체 트랙 Pond5 메타데이터 일괄 생성"""
    results = []
    for track in track_list:
        try:
            meta = generate_pond5_metadata(
                file_name=track.get("file_name", ""),
                track_mood=track.get("track_mood", "chill"),
                genre=track.get("genre", "lofi")
            )
            results.append(meta)
            print(f"생성 완료: {meta['title']}")
        except Exception as e:
            print(f"오류 건너뜀: {track.get('file_name', '')} → {e}")
            continue
    return results


if __name__ == "__main__":
    from pathlib import Path
    import json

    # Pond5 메타데이터 생성
    music_files = list(Path("music/").glob("*.mp3"))
    tracks = []
    for f in music_files:
        parts = f.stem.split(".")
        name = parts[-1].strip() if len(parts) > 1 else f.stem
        genre = "citypop" if any(k in name.lower() for k in ["city", "tokyo", "neon", "midnight", "cassette"]) else "lofi"
        tracks.append({
            "file_name": f.name,
            "genre": genre,
            "track_mood": name
        })

    print(f"총 {len(tracks)}개 Pond5 메타데이터 생성 시작...")
    pond5_list = batch_generate_pond5(tracks)

    with open("pond5_metadata.json", "w", encoding="utf-8") as f:
        json.dump(pond5_list, f, ensure_ascii=False, indent=2)

    print(f"완료! pond5_metadata.json 저장됨")