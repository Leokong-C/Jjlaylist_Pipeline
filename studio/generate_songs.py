"""
generate_songs.py · STEP 2 — Mureka 공식 API로 내 목소리 곡 생성
──────────────────────────────────────────────────────────────
(기존 mureka_generator.py의 /v1/song/generate · /v1/song/query 로직을 재사용)

[최초 1회] 내 목소리 등록
  python generate_songs.py --upload-voice my_voice.mp3
  → 15~30초, 반주 없는 깨끗한 노래 녹음 (MP3/M4A, 10MB 미만)
  → 받은 vocal_id가 voice.json에 저장됨

[릴리스마다] plan.json의 가사·스타일로 곡별 후보 2개 생성
  python generate_songs.py --slug <slug>
  python generate_songs.py --slug <slug> --only 2,4      # 특정 곡만 재생성
  python generate_songs.py --slug <slug> --dry-run       # 요청 바디만 출력
  → inbox/<slug>/candidates/NN_a.mp3, NN_b.mp3

필요: .env 에 MUREKA_API_KEY=...  (platform.mureka.ai 에서 발급, 웹 구독 크레딧과 별도 과금)

⚠️ 비공식 계정 연동 서비스(useapi.net 등)는 쓰지 않습니다 — Suno 쿠키 방식과 같은 붕괴 위험.
"""
import argparse, json, os, time
from pathlib import Path
import requests
from config import BASE_DIR, INBOX_DIR, release_dir

API_BASE   = os.getenv("MUREKA_API_BASE", "https://api.mureka.ai")
MODEL      = os.getenv("MUREKA_MODEL", "auto")
VOICE_FILE = BASE_DIR / "voice.json"
POLL_SEC, TIMEOUT_SEC = 5, 420

def api_key() -> str:
    key = os.getenv("MUREKA_API_KEY", "")
    env = BASE_DIR / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("MUREKA_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("MUREKA_API_KEY가 없습니다 (.env 또는 환경변수).")
    return key

def H(json_body=True):
    h = {"Authorization": f"Bearer {api_key()}"}
    if json_body:
        h["Content-Type"] = "application/json"
    return h

# ── 1. 목소리 등록 ────────────────────────────────────────────────
def upload_voice(path: Path):
    size = path.stat().st_size
    if size > 10 * 1024 * 1024:
        raise SystemExit("10MB 미만으로 줄여주세요.")
    with open(path, "rb") as f:
        r = requests.post(f"{API_BASE}/v1/files/upload", headers=H(False),
                          files={"file": (path.name, f)}, data={"purpose": "vocal"}, timeout=120)
    if r.status_code >= 400:
        raise SystemExit(f"업로드 실패 {r.status_code}: {r.text[:300]}\n"
                         "→ platform.mureka.ai 문서에서 files/upload의 purpose 값을 확인하세요.")
    vid = r.json()["id"]
    VOICE_FILE.write_text(json.dumps({"vocal_id": vid, "source": path.name,
                                      "created": time.strftime("%Y-%m-%d %H:%M")}, indent=2), encoding="utf-8")
    print(f"✅ 내 목소리 등록 완료 → vocal_id={vid} (voice.json 저장)")

def vocal_id():
    if not VOICE_FILE.exists():
        raise SystemExit("voice.json 없음 → 먼저 --upload-voice 로 목소리를 등록하세요.")
    return json.loads(VOICE_FILE.read_text(encoding="utf-8"))["vocal_id"]

# ── 2. 곡 생성 ────────────────────────────────────────────────────
def request_song(track: dict, vid: str, dry: bool):
    body = {"lyrics": track["lyrics"], "prompt": track["style"][:1000],
            "model": MODEL, "vocal_id": vid}
    if dry:
        print(json.dumps({k: (v[:80] + "…" if isinstance(v, str) and len(v) > 80 else v)
                          for k, v in body.items()}, ensure_ascii=False, indent=1))
        return None
    r = requests.post(f"{API_BASE}/v1/song/generate", headers=H(), json=body, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"생성 요청 실패 {r.status_code}: {r.text[:300]}")
    return r.json()["id"]

def poll(task_id: str) -> dict:
    t0 = time.time()
    while True:
        r = requests.get(f"{API_BASE}/v1/song/query/{task_id}", headers=H(), timeout=15)
        r.raise_for_status()
        data = r.json(); st = data.get("status", "")
        if st == "succeeded":
            return data
        if st in ("failed", "canceled", "timeouted"):
            raise RuntimeError(f"{task_id} {st}: {data.get('failed_reason','')}")
        if time.time() - t0 > TIMEOUT_SEC:
            raise TimeoutError(task_id)
        print(f"    ⏳ {int(time.time()-t0)}s ({st})", end="\r"); time.sleep(POLL_SEC)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upload-voice", type=Path)
    ap.add_argument("--slug")
    ap.add_argument("--only", default="", help="재생성할 곡 번호 (예: 2,4)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.upload_voice:
        return upload_voice(a.upload_voice)
    if not a.slug:
        raise SystemExit("--slug 또는 --upload-voice 를 지정하세요.")

    d = release_dir(a.slug)
    plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
    out = INBOX_DIR / a.slug / "candidates"; out.mkdir(parents=True, exist_ok=True)
    only = {int(x) for x in a.only.split(",") if x}
    vid = "DRY_RUN_VOCAL_ID" if a.dry_run and not VOICE_FILE.exists() else vocal_id()

    # 동시 요청 후 순차 폴링 (곡당 ~45초)
    tasks = {}
    for t in plan["tracks"]:
        if only and t["no"] not in only:
            continue
        print(f"▶ {t['no']:02d}. {t['title']}")
        tid = request_song(t, vid, a.dry_run)
        if tid:
            tasks[t["no"]] = tid
    for no, tid in tasks.items():
        try:
            data = poll(tid)
        except Exception as e:
            print(f"  ❌ {no:02d} 실패: {e}"); continue
        for ch, c in zip("ab", data.get("choices", [])):
            url = c.get("mp3_url") or c.get("url") or c.get("flac_url")
            dst = out / f"{no:02d}_{ch}.mp3"
            dst.write_bytes(requests.get(url, timeout=120).content)
            print(f"  ✅ {dst.name}")
    if tasks:
        print(f"\n🎧 후보를 들어보고 고르세요: {out}\n"
              f"   python ingest.py --slug {a.slug} --pick \"1a,2b,3a,...\"   (또는 --auto)")

if __name__ == "__main__":
    main()
