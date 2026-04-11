"""
setup_github.py  ·  J_Jlaylist
────────────────────────────────────────────────────────────────
GitHub Actions 마이그레이션 로컬 셋업 헬퍼

실행:
  python setup_github.py

기능:
  1. token.pickle → base64 인코딩 출력 (GitHub Secret 등록용)
  2. .env 파일 템플릿 생성
  3. .gitignore 업데이트 (민감 파일 제외)
  4. 필수 디렉토리 구조 생성
  5. 설정 체크리스트 출력
"""

import base64
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def encode_token_pickle() -> str | None:
    """token.pickle을 base64로 인코딩"""
    token_path = BASE_DIR / "token.pickle"
    if not token_path.exists():
        print("⚠️  token.pickle 없음 — 먼저 uploader.py를 로컬에서 한 번 실행하세요.")
        return None
    encoded = base64.b64encode(token_path.read_bytes()).decode()
    print("\n" + "="*60)
    print("✅ TOKEN_PICKLE_B64 (GitHub Secrets에 등록)")
    print("="*60)
    print(encoded)
    print("="*60)

    # 파일로도 저장 (복붙 편의)
    out = BASE_DIR / "token_b64.txt"
    out.write_text(encoded)
    print(f"\n📄 파일로도 저장됨: {out}")
    print("   ⚠️  등록 후 token_b64.txt 반드시 삭제!\n")
    return encoded


def create_env_template():
    """로컬 .env 파일 템플릿 생성"""
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        print("ℹ️  .env 파일이 이미 존재합니다. 덮어쓰지 않습니다.")
        return

    template = """\
# J_Jlaylist 환경변수
# ⚠️ 이 파일은 절대 git에 올리지 마세요!

ANTHROPIC_API_KEY=sk-ant-xxxxxxxxxxxxxxxxxxxxxxxx
POND5_USER=your_pond5_username
POND5_PASS=your_pond5_password
"""
    env_path.write_text(template, encoding="utf-8")
    print(f"✅ .env 템플릿 생성됨: {env_path}")


def update_gitignore():
    """민감 파일 .gitignore 처리"""
    gitignore_path = BASE_DIR / ".gitignore"
    entries_to_add = [
        "# 민감 파일",
        "token.pickle",
        "token_b64.txt",
        ".env",
        "*.pickle",
        "",
        "# OS",
        ".DS_Store",
        "Thumbs.db",
        "",
        "# Python",
        "__pycache__/",
        "*.pyc",
        "*.pyo",
        "",
        "# 대용량 출력물 (로컬 전용)",
        "output/mixes/*.mp4",
        "output/shorts/*.mp4",
        "music/*.mp3",
        "music/processed/",
        "assets/backgrounds/",
    ]

    existing = gitignore_path.read_text(encoding="utf-8") if gitignore_path.exists() else ""
    added = []
    for entry in entries_to_add:
        if entry and entry not in existing:
            added.append(entry)

    if added:
        with open(gitignore_path, "a", encoding="utf-8") as f:
            f.write("\n" + "\n".join(entries_to_add))
        print(f"✅ .gitignore 업데이트 완료")
    else:
        print("ℹ️  .gitignore 이미 최신 상태")


def create_dirs():
    """필수 디렉토리 생성"""
    dirs = [
        ".github/workflows",
        "music",
        "music/processed",
        "output/mixes",
        "output/shorts",
        "output/reels",
        "output/blog_posts",
        "output/thumbnails",
        "assets/backgrounds",
        "assets/thumbnails",
        "idea",
    ]
    for d in dirs:
        path = BASE_DIR / d
        path.mkdir(parents=True, exist_ok=True)
        # .gitkeep (빈 폴더 유지)
        keep = path / ".gitkeep"
        if not keep.exists() and not any(path.iterdir()):
            keep.touch()

    print("✅ 디렉토리 구조 생성 완료")


def print_checklist():
    """GitHub Actions 설정 체크리스트"""
    print("""
╔══════════════════════════════════════════════════════════════╗
║         GitHub Actions 마이그레이션 체크리스트               ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  1. GitHub Secrets 등록 (Settings → Secrets → Actions)      ║
║     □ TOKEN_PICKLE_B64  ← token_b64.txt 내용                ║
║     □ ANTHROPIC_API_KEY ← Claude API 키                     ║
║     □ POND5_USER        ← Pond5 아이디                      ║
║     □ POND5_PASS        ← Pond5 비밀번호                    ║
║                                                              ║
║  2. 파일 복사                                                ║
║     □ pipeline.yml → .github/workflows/pipeline.yml         ║
║     □ config.py → 프로젝트 루트                             ║
║     □ mureka_prompt_generator.py → 프로젝트 루트            ║
║                                                              ║
║  3. config.py 임포트로 경로 변환                             ║
║     □ uploader.py   — token.pickle 경로                     ║
║     □ mixer.py      — music/, output/ 경로                  ║
║     □ batch_mix.py  — processed/ 경로                       ║
║                                                              ║
║  4. 첫 테스트                                                ║
║     □ git push → Actions 탭에서 실행 확인                   ║
║     □ workflow_dispatch로 수동 테스트                        ║
║                                                              ║
║  5. 워크플로우 확인 후 token_b64.txt 삭제!                  ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
""")


def main():
    print("🚀 J_Jlaylist GitHub Actions 마이그레이션 셋업\n")

    create_dirs()
    create_env_template()
    update_gitignore()
    encode_token_pickle()
    print_checklist()


if __name__ == "__main__":
    main()