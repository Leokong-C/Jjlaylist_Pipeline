"""config.py · J_Jlaylist Studio v2 — 공통 경로·설정"""
import os, sys, io
from pathlib import Path

if sys.platform == "win32":  # CMD 한글 출력
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

BASE_DIR     = Path(__file__).resolve().parent
BIBLE_FILE   = BASE_DIR / "bible.yaml"          # 세계관 설정 (사람이 작성)
RELEASES_DIR = BASE_DIR / "releases"            # 릴리스별 작업 폴더
INBOX_DIR    = BASE_DIR / "inbox"               # 생성 후보·직접 넣은 음원
TOKEN_PATH   = Path(os.getenv("YT_TOKEN_PATH", BASE_DIR.parent / "token.pickle"))   # 저장소 루트의 기존 토큰
SECRET_FILE  = Path(os.getenv("YT_CLIENT_SECRET", BASE_DIR / "client_secret.json"))

# 모델명은 한 곳에서만 관리 (deprecate 대비)
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

FFMPEG  = os.getenv("FFMPEG", "ffmpeg")
FFPROBE = os.getenv("FFPROBE", "ffprobe")
TARGET_LUFS = -14          # YouTube·스트리밍 기준 라우드니스

# 자막/타이틀 폰트 (Windows 기본 맑은고딕 → 없으면 Noto)
FONT_CANDIDATES = [
    os.getenv("STUDIO_FONT", ""),
    r"C:\Windows\Fonts\malgunbd.ttf",
    r"C:\Windows\Fonts\malgun.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
]
def font_path() -> str:
    for p in FONT_CANDIDATES:
        if p and Path(p).exists():
            return p
    raise FileNotFoundError("한글 폰트를 찾지 못했습니다. STUDIO_FONT 환경변수로 지정하세요.")

def anthropic_key() -> str:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    env = BASE_DIR / ".env"
    if not key and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY가 없습니다 (.env 또는 환경변수).")
    return key

def release_dir(slug: str) -> Path:
    d = RELEASES_DIR / slug
    for sub in ("", "audio", "art", "video", "shorts"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d
