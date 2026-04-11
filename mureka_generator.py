"""
mureka_generator.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
Mureka API로 시티팝 음악 자동 생성 → music/ 저장 → batch_mix.py 연동

파이프라인:
  Mureka API → MP3 다운로드 → music/ 저장 → batch_mix.py 실행

사용법:
  python mureka_generator.py --count 10          # 10곡 생성 (instrumental)
  python mureka_generator.py --count 10 --vocal  # 보컬 포함
  python mureka_generator.py --count 10 --mix    # 생성 후 바로 믹싱까지
  python mureka_generator.py --balance           # 잔액 확인
  python mureka_generator.py --preview           # 프롬프트 목록만 확인

필요 환경변수:
  set MUREKA_API_KEY=your_api_key_here

API 비용 참고:
  - 1회 생성 = 2트랙 반환 (1곡 생성 요청 → 2개 파일)
  - 평균 생성 시간: 45초
  - 최대 동시 요청: 10개
"""

import os, json, time, argparse, requests
from pathlib import Path
from datetime import datetime

# ── 경로 ─────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
MUSIC_DIR = BASE_DIR / "music"
LOG_FILE  = BASE_DIR / "mureka_log.json"

MUSIC_DIR.mkdir(parents=True, exist_ok=True)

# ── API 설정 ──────────────────────────────────────────────────────────────
API_BASE    = "https://api.mureka.ai"
API_KEY     = os.environ.get("MUREKA_API_KEY", "")
POLL_SEC    = 5    # 폴링 간격 (초)
TIMEOUT_SEC = 180  # 최대 대기 시간 (초)

# ── J_Jlaylist 시티팝 프롬프트 풀 ────────────────────────────────────────
# 분위기별로 다양하게 구성 — 1회 생성마다 랜덤 선택
CITYPOP_PROMPTS = [
    # 밤 드라이브
    {
        "prompt": "japanese city pop, 80s urban pop, night drive, neon lights, "
                  "smooth synth bass, electric guitar, female vocal, 110 bpm, "
                  "melancholic, sophisticated, reverb",
        "mood": "night_drive",
    },
    # 카페 / 비
    {
        "prompt": "japanese city pop, lofi, rainy cafe, warm piano, soft drums, "
                  "mellow, nostalgic, female vocal, 95 bpm, smooth, cozy, "
                  "80s pop, synth pad",
        "mood": "cafe_rain",
    },
    # 새벽 감성
    {
        "prompt": "japanese city pop, 80s, late night, melancholic, slow tempo, "
                  "synth bass, saxophone, female vocal, 90 bpm, urban, "
                  "sophisticated, emotional, chorus effect",
        "mood": "melancholy",
    },
    # 여름 / 도쿄
    {
        "prompt": "japanese city pop, summer, tokyo, upbeat, funk, "
                  "slap bass, brass section, female vocal, 120 bpm, "
                  "80s urban pop, bright, energetic, disco influence",
        "mood": "neon_city",
    },
    # 새벽 / 여명
    {
        "prompt": "japanese city pop, dawn, morning light, hopeful, "
                  "acoustic guitar, soft synth, female vocal, 100 bpm, "
                  "80s pop, gentle, warm, ambient, city morning",
        "mood": "dawn_morning",
    },
    # 미드나잇
    {
        "prompt": "japanese city pop, midnight, 80s, synthwave influence, "
                  "deep synth bass, electric piano, female vocal, 105 bpm, "
                  "mysterious, urban, neon, late night",
        "mood": "midnight_drive",
    },
    # 로파이 시티팝
    {
        "prompt": "lofi city pop, japanese, lo-fi hip hop, vinyl crackle, "
                  "mellow guitar, soft beat, 85 bpm, nostalgic, "
                  "study music, calm, 80s vibe, warm",
        "mood": "cafe_rain",
    },
    # 어반팝
    {
        "prompt": "japanese urban pop, 80s, sophisticated, adult contemporary, "
                  "smooth jazz influence, synth, female vocal, 112 bpm, "
                  "city pop, polished, studio quality",
        "mood": "neon_city",
    },
]

INSTRUMENTAL_PROMPTS = [
    {
        "prompt": "japanese city pop instrumental, 80s, night drive, "
                  "synth bass, electric guitar, saxophone, 110 bpm, "
                  "no vocal, background music, smooth, urban",
        "mood": "night_drive",
    },
    {
        "prompt": "lofi city pop instrumental, japanese, soft piano, "
                  "light drums, 90 bpm, no vocal, study bgm, "
                  "nostalgic, warm, vinyl texture",
        "mood": "cafe_rain",
    },
    {
        "prompt": "japanese city pop bgm, 80s urban, synth, bass, "
                  "no vocal, background music, 100 bpm, "
                  "sophisticated, melodic, instrumental",
        "mood": "melancholy",
    },
]


# ── API 헬퍼 ─────────────────────────────────────────────────────────────
def headers() -> dict:
    if not API_KEY:
        raise ValueError(
            "MUREKA_API_KEY 환경변수 없음\n"
            "  set MUREKA_API_KEY=your_api_key_here"
        )
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type":  "application/json",
    }


def check_balance() -> dict:
    """잔액 조회"""
    r = requests.get(f"{API_BASE}/v1/account/billing", headers=headers(), timeout=10)
    r.raise_for_status()
    return r.json()


def generate_song(prompt: str, lyrics: str = None, model: str = "auto") -> str:
    """곡 생성 요청 → task_id 반환"""
    body = {"prompt": prompt, "model": model}
    if lyrics:
        body["lyrics"] = lyrics

    r = requests.post(
        f"{API_BASE}/v1/song/generate",
        headers=headers(),
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    data = r.json()
    return data["id"]  # task_id


def generate_instrumental(prompt: str, model: str = "auto") -> str:
    """인스트루멘탈 생성 요청 → task_id 반환"""
    body = {"prompt": prompt, "model": model}
    r = requests.post(
        f"{API_BASE}/v1/instrumental/generate",
        headers=headers(),
        json=body,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["id"]


def poll_task(task_id: str, is_instrumental: bool = False) -> dict:
    """
    task 완료까지 폴링
    반환: {"flac_url": ..., "mp3_url": ..., "title": ...} 형태의 choices 리스트
    """
    endpoint = (
        f"{API_BASE}/v1/instrumental/query/{task_id}"
        if is_instrumental
        else f"{API_BASE}/v1/song/query/{task_id}"
    )
    start = time.time()
    while True:
        r    = requests.get(endpoint, headers=headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
        status = data.get("status", "")

        if status == "succeeded":
            return data
        elif status in ("failed", "canceled"):
            raise RuntimeError(f"Task {task_id} 실패: {status}")
        elif time.time() - start > TIMEOUT_SEC:
            raise TimeoutError(f"Task {task_id} 타임아웃 ({TIMEOUT_SEC}초)")

        elapsed = int(time.time() - start)
        print(f"  ⏳ {elapsed}초... (status: {status})", end="\r")
        time.sleep(POLL_SEC)


def download_mp3(url: str, dest: Path) -> Path:
    """MP3 URL → 파일 다운로드"""
    r = requests.get(url, timeout=60, stream=True)
    r.raise_for_status()
    dest.write_bytes(r.content)
    return dest


# ── 로그 ─────────────────────────────────────────────────────────────────
def load_log() -> list:
    if LOG_FILE.exists():
        with open(LOG_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_log(log: list):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ── 파일명 생성 ───────────────────────────────────────────────────────────
def make_filename(title: str, index: int, mood: str) -> str:
    """
    Mureka가 반환하는 title + 순번으로 파일명 생성
    """
    # 특수문자 제거
    import re
    clean = re.sub(r'[<>:"/\\|?*]', "", title).strip()
    if not clean:
        clean = f"{mood}_track_{index:03d}"
    return f"{clean}.mp3"


# ── 단일 곡 생성 전체 흐름 ────────────────────────────────────────────────
def create_one_track(prompt_cfg: dict, index: int,
                     is_instrumental: bool) -> list:
    """
    1회 API 요청 → 2개 트랙 반환 → 다운로드 → music/ 저장
    반환: 저장된 파일 경로 리스트
    """
    prompt = prompt_cfg["prompt"]
    mood   = prompt_cfg.get("mood", "all")

    print(f"\n[{index}] 생성 중 | mood: {mood}")
    print(f"  프롬프트: {prompt[:60]}...")

    # 생성 요청
    if is_instrumental:
        task_id = generate_instrumental(prompt)
    else:
        task_id = generate_song(prompt)

    print(f"  task_id: {task_id}")

    # 완료 대기
    result = poll_task(task_id, is_instrumental=is_instrumental)
    print()  # 줄바꿈 (⏳ 덮어쓰기 후)

    # choices에서 MP3 URL 추출 (1 task = 2 tracks)
    choices = result.get("choices", [])
    saved   = []

    for j, choice in enumerate(choices):
        mp3_url = choice.get("mp3_url") or choice.get("flac_url", "")
        title   = choice.get("title", f"track_{index:03d}_{j+1}")

        if not mp3_url:
            print(f"  ⚠️  {j+1}번 트랙 URL 없음")
            continue

        filename = make_filename(title, index * 10 + j, mood)
        dest     = MUSIC_DIR / filename

        # 중복 파일명 처리
        counter = 1
        while dest.exists():
            stem = dest.stem
            dest = MUSIC_DIR / f"{stem}_{counter}.mp3"
            counter += 1

        print(f"  ⬇️  다운로드: {filename}")
        download_mp3(mp3_url, dest)
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  ✅ 저장: {dest.name} ({size_mb:.1f}MB)")
        saved.append(str(dest))

    return saved


# ── 메인 실행 ─────────────────────────────────────────────────────────────
def main():
    p = argparse.ArgumentParser(description="J_Jlaylist Mureka 음악 자동 생성")
    p.add_argument("--count",   type=int, default=5,
                   help="생성할 곡 수 (기본 5, 1회 요청당 2트랙 반환)")
    p.add_argument("--vocal",   action="store_true",
                   help="보컬 포함 (기본: 인스트루멘탈)")
    p.add_argument("--mix",     action="store_true",
                   help="생성 완료 후 batch_mix.py 자동 실행")
    p.add_argument("--balance", action="store_true",
                   help="Mureka API 잔액 확인")
    p.add_argument("--preview", action="store_true",
                   help="프롬프트 목록만 확인 (API 호출 안 함)")
    args = p.parse_args()

    # 잔액 확인
    if args.balance:
        try:
            info = check_balance()
            print(f"\n💳 Mureka API 잔액")
            print(json.dumps(info, indent=2, ensure_ascii=False))
        except Exception as e:
            print(f"❌ 잔액 조회 실패: {e}")
        return

    # 프롬프트 미리보기
    pool = CITYPOP_PROMPTS if args.vocal else INSTRUMENTAL_PROMPTS + CITYPOP_PROMPTS
    if args.preview:
        print(f"\n📋 사용 가능한 프롬프트 ({len(pool)}개)")
        for i, cfg in enumerate(pool, 1):
            print(f"\n[{i}] mood: {cfg['mood']}")
            print(f"  {cfg['prompt'][:80]}...")
        print(f"\n생성 예정: {args.count}회 요청 → 최대 {args.count * 2}트랙")
        return

    # ── 생성 시작 ──────────────────────────────────────────────────────────
    import random
    is_instrumental = not args.vocal

    print(f"\n🎵 Mureka 음악 생성 시작")
    print(f"   요청 수: {args.count}회 → 최대 {args.count * 2}트랙")
    print(f"   타입: {'보컬' if args.vocal else '인스트루멘탈'}")
    print(f"   저장: {MUSIC_DIR}")
    print("=" * 60)

    log      = load_log()
    all_saved = []

    for i in range(1, args.count + 1):
        # 프롬프트 순환 선택 (랜덤하지 않고 다양하게)
        prompt_cfg = pool[(i - 1) % len(pool)]

        try:
            saved = create_one_track(
                prompt_cfg=prompt_cfg,
                index=i,
                is_instrumental=is_instrumental,
            )
            all_saved.extend(saved)
            log.append({
                "index":   i,
                "mood":    prompt_cfg["mood"],
                "files":   saved,
                "created": datetime.now().isoformat(),
            })
            save_log(log)

        except Exception as e:
            print(f"\n  ❌ {i}번 요청 실패: {e}")

        # 연속 요청 간 1초 대기
        if i < args.count:
            time.sleep(1.0)

    # ── 결과 요약 ──────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"✅ 생성 완료: {len(all_saved)}트랙 → {MUSIC_DIR}")
    for f in all_saved:
        print(f"   {Path(f).name}")

    # ── 믹싱 연동 ──────────────────────────────────────────────────────────
    if args.mix and all_saved:
        # music/ 폴더의 대기 중 MP3 수 확인
        pending = list(MUSIC_DIR.glob("*.mp3"))
        print(f"\n🎚  music/ 대기 중: {len(pending)}곡")

        if len(pending) >= 10:
            batches = len(pending) // 10
            print(f"   → {batches}개 배치 처리 가능")
            confirm = input("batch_mix.py 실행? (yes): ").strip().lower()
            if confirm == "yes":
                import subprocess
                subprocess.run(["python", "batch_mix.py"], check=False)
        else:
            need = 10 - len(pending)
            print(f"   → 배치 실행까지 {need}곡 더 필요")
            print(f"   → python mureka_generator.py --count {need} --mix")


if __name__ == "__main__":
    main()