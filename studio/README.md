# J_Jlaylist Studio v2 — 세계관형 AI 밴드 파이프라인 (Mureka + 내 목소리)

사람이 할 일은 **세계관 설정 · 가사 검토 · 후보곡 고르기 · 커버**뿐입니다.

```
bible.yaml → plan_release → generate_songs → ingest --pick → render_album → publish
  (사람)      Claude 기획      Mureka API       (사람이 선택)     영상·쇼츠       YouTube
                              + 내 vocal_id                                  (AI 고지 자동)
```

## 설치 (Windows CMD)
```
pip install -r requirements.txt
```
`.env` 파일:
```
ANTHROPIC_API_KEY=...
MUREKA_API_KEY=...        # platform.mureka.ai 발급 (기존 키 재사용 가능)
```
- 로컬 업로드 시 저장소 루트의 기존 `token.pickle`을 씁니다 (다른 경로면 `set YT_TOKEN_PATH=...`)
- FFmpeg가 PATH에 있어야 합니다

## 최초 1회: 내 목소리 등록
반주 없이 **15~30초** 노래를 녹음하세요 (MP3/M4A, 10MB 미만). 만들 장르 톤으로 부르는 게 좋습니다.
```
python generate_songs.py --upload-voice my_voice.mp3
```
`voice.json`(vocal_id)은 커밋해도 됩니다 — 비밀값이 아니라 ID입니다.

## 릴리스 1회 사이클
| 단계 | 명령 | 사람이 할 일 |
|---|---|---|
| 1 | `python plan_release.py --theme "주제"` | `lyrics_sheet.md` 검토, 수정은 `plan.json`에서 |
| 2 | `python generate_songs.py --slug <slug> --dry-run` → 실제 실행 | — |
| 3 | `python ingest.py --slug <slug> --pick "1a,2b,3a,4a,5b"` | `inbox/<slug>/candidates/` 후보 듣고 고르기. 마음에 안 들면 `generate_songs.py --only 2` |
| 4 | — | `releases/<slug>/art/cover.png` (정사각형) |
| 5 | `python render_album.py --slug <slug>` | 쇼츠 구간 조정: `--hook "2:61,4:48"` |
| 6 | `git push` (아래 업로드 자동화) — 로컬에서 직접 올리려면 `python publish.py --slug <slug>` | Studio에서 최종 확인 |

## 업로드 자동화 (GitHub Actions → @J_Jlaylist)
`studio/releases/<slug>/`에 **plan.json + audio/ + art/cover.png**가 갖춰진 상태로 push하면
`.github/workflows/studio_publish.yml`이 렌더 → 업로드를 자동으로 합니다.

```
python ingest.py --slug <slug> --pick "1a,2b,3a,4a,5b"
(cover.png 넣기)
git add studio/releases/<slug>
git commit -m "release: <slug>"
git push
```
- **업로드 전에 Slack으로 승인 요청이 옵니다.** 곡 목록·후렴·예약 시간을 확인하고 *검토 · 승인하기* → GitHub에서 **Approve and deploy**를 눌러야 업로드됩니다 (GitHub 모바일 앱에서도 가능). 미리보기 영상은 실행 페이지 Artifacts에 있습니다.
- 한 번 승인한 릴리스의 남은 쇼츠는 다시 묻지 않고 매일 이어서 올립니다.
- 업로드 전 인증 채널이 J_Jlaylist인지 확인하고, 다르면 중단합니다.
- 모든 영상은 **비공개 + 예약 공개**: 풀앨범은 다음날 21:00 KST, 쇼츠는 그 다음날부터 하루 1개씩.
- 하루 6개(쿼터 한도) 초과분은 매일 13:23 KST 정기 실행 때 이어서 올립니다.
- 업로드된 video id는 `plan.json`에 기록돼 중복 업로드가 없습니다. 결과는 메일로 옵니다.
- 시크릿: 기존 `TOKEN_PICKLE_B64` + 새로 `SLACK_WEBHOOK_URL`
- 최초 1회 설정: Settings → Environments → `youtube-publish` 생성 → Required reviewers에 본인 추가
- 수동 실행: Actions → *Studio Release Publish* → Run workflow (dry-run 옵션 있음)

## 설정
- `set CLAUDE_MODEL=...` / `set MUREKA_MODEL=...` — 모델명은 환경변수 한 곳에서 관리
- 첫 실제 호출 전 platform.mureka.ai 문서에서 `files/upload`(purpose=vocal)와 `song/generate`의 `vocal_id` 파라미터명을 한 번 확인하세요. 다르면 `generate_songs.py`의 해당 줄만 고치면 됩니다.

## 의도적으로 자동화하지 않은 것
- **후보곡 선택**: 사람이 고르는 단계가 '사람이 만든 작품'의 근거이자 품질 관리입니다.
- **음원 유통(DistroKid 등)**: API가 없어 수동입니다. 메타데이터는 `plan.json`에 모두 들어 있습니다.
- **비공식 계정 연동 API**: 쓰지 않습니다 (Suno 쿠키 방식과 같은 붕괴 위험).
