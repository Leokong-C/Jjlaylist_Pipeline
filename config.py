"""
config.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
크로스플랫폼 경로 설정 — Windows / Linux(GitHub Actions) 자동 감지

어느 컴퓨터에서 실행해도 경로가 자동으로 맞춰집니다.
"""

import os
import sys
from pathlib import Path

# ── 프로젝트 루트 (이 파일 기준) ────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent

# ── OS 감지 ─────────────────────────────────────────────────────────────
IS_WINDOWS = sys.platform == "win32"
IS_CI      = os.environ.get("CI") == "true"   # GitHub Actions 환경

# ── 주요 경로 ────────────────────────────────────────────────────────────
MUSIC_DIR      = BASE_DIR / "music"
PROCESSED_DIR  = MUSIC_DIR / "processed"
OUTPUT_DIR     = BASE_DIR / "output"
MIXES_DIR      = OUTPUT_DIR / "mixes"
SHORTS_DIR     = OUTPUT_DIR / "shorts"
REELS_DIR      = OUTPUT_DIR / "reels"
BLOG_DIR       = OUTPUT_DIR / "blog_posts"
THUMB_DIR      = OUTPUT_DIR / "thumbnails"
ASSETS_DIR     = BASE_DIR / "assets"
BG_DIR         = ASSETS_DIR / "backgrounds"
TOKEN_PATH     = BASE_DIR / "token.pickle"
LOG_FILE       = BASE_DIR / "mix_upload_log.json"
BATCH_LOG      = BASE_DIR / "batch_log.json"
POND5_META     = BASE_DIR / "pond5_metadata.json"
PROMPT_DIR     = BASE_DIR / "idea"            # Mureka 프롬프트 번들

# ── 디렉토리 자동 생성 ───────────────────────────────────────────────────
def ensure_dirs():
    for d in [MUSIC_DIR, PROCESSED_DIR, MIXES_DIR, SHORTS_DIR,
              REELS_DIR, BLOG_DIR, THUMB_DIR, BG_DIR, PROMPT_DIR]:
        d.mkdir(parents=True, exist_ok=True)

# ── API 키 (환경변수 우선, .env 파일 fallback) ───────────────────────────
def get_anthropic_key() -> str:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("ANTHROPIC_API_KEY="):
                    key = line.split("=", 1)[1].strip()
    if not key:
        raise ValueError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
    return key

def get_pond5_creds() -> tuple[str, str]:
    user = os.environ.get("POND5_USER", "")
    pwd  = os.environ.get("POND5_PASS", "")
    if not user:
        env_file = BASE_DIR / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("POND5_USER="):
                    user = line.split("=", 1)[1].strip()
                elif line.startswith("POND5_PASS="):
                    pwd = line.split("=", 1)[1].strip()
    return user, pwd

# ── 업로드 스케줄 ────────────────────────────────────────────────────────
UPLOAD_HOUR_MIX    = 9    # KST 오전 9시 (믹스 영상)
UPLOAD_HOUR_SHORTS = 18   # KST 오후 6시 (Shorts)
DAYS_INTERVAL      = 2    # 2일 간격

# ── FFmpeg 경로 (Windows는 PATH에 있어야 함) ─────────────────────────────
FFMPEG_BIN  = "ffmpeg"
FFPROBE_BIN = "ffprobe"

# ── YouTube API 쿼터 안전 한도 ───────────────────────────────────────────
YT_DAILY_QUOTA    = 10_000
YT_UPLOAD_COST    = 1_600
YT_MAX_UPLOADS    = YT_DAILY_QUOTA // YT_UPLOAD_COST  # = 6개/일

if __name__ == "__main__":
    ensure_dirs()
    print(f"BASE_DIR  : {BASE_DIR}")
    print(f"IS_WINDOWS: {IS_WINDOWS}")
    print(f"IS_CI     : {IS_CI}")
    print(f"TOKEN_PATH: {TOKEN_PATH} (exists={TOKEN_PATH.exists()})")