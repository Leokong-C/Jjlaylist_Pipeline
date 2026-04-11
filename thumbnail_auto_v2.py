"""
thumbnail_auto_v2.py
"""
import os, sys, json, pickle, argparse, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import anthropic

BASE_DIR      = Path(__file__).parent
THUMB_BG_DIR  = BASE_DIR / "thumbnails" / "backgrounds"
THUMB_OUT_DIR = BASE_DIR / "thumbnails" / "output_v2"
ASSETS_DIR    = BASE_DIR / "assets" / "thumbnails"
BATCH_LOG     = BASE_DIR / "batch_log.json"
TOKEN_PATH    = BASE_DIR / "token.pickle"
CLIENT_SECRET = BASE_DIR / "client_secret.json"
SCOPES        = ["https://www.googleapis.com/auth/youtube"]
THUMB_W, THUMB_H = 1280, 720

MOOD_DIRS = ["night_drive","cafe_rain","melancholy","dawn_morning","neon_city","midnight_drive"]
MOOD_PHRASES = {
    "night_drive":    ["새벽 드라이브","밤을 달리며","네온 속으로"],
    "cafe_rain":      ["비 오는 카페","창문 너머 빗소리","커피 한 잔의 감성"],
    "melancholy":     ["아련한 밤","혼자인 새벽","그리운 도쿄"],
    "dawn_morning":   ["여명의 도쿄","새벽 5시","동이 트는 시간"],
    "neon_city":      ["네온의 도시","도쿄의 밤","빛나는 새벽"],
    "midnight_drive": ["자정의 드라이브","새벽 2시","밤의 끝에서"],
}

def find_korean_font(size):
    for path in ["C:/Windows/Fonts/malgunbd.ttf","C:/Windows/Fonts/malgun.ttf",
                 "C:/Windows/Fonts/NanumGothicBold.ttf","C:/Windows/Fonts/gulim.ttc"]:
        if Path(path).exists():
            try: return ImageFont.truetype(path, size)
            except: continue
    return ImageFont.load_default()

def find_background(mood, batch_num):
    for d in [THUMB_BG_DIR / mood, ASSETS_DIR]:
        if d.exists():
            c = list(d.glob("*.jpg")) + list(d.glob("*.png"))
            if c: return c[batch_num % len(c)]
    return None

def generate_phrase(mix_title, mood):
    try:
        client = anthropic.Anthropic()
        resp = client.messages.create(
            model="claude-opus-4-5", max_tokens=30,
            messages=[{"role":"user","content":
                f"YouTube 썸네일용 한국어 감성 문구 6자 이내, 명사형:\n테마:{mix_title}\n무드:{mood}\n문구만 출력"}]
        )
        return resp.content[0].text.strip().replace("```","")[:10]
    except:
        return MOOD_PHRASES.get(mood,["도쿄의 밤"])[0]

def make_thumbnail(batch_num, mix_title, phrase, output_path):
    mood    = MOOD_DIRS[batch_num % len(MOOD_DIRS)]
    bg_path = find_background(mood, batch_num)
    img = Image.open(bg_path).convert("RGB").resize((THUMB_W,THUMB_H),Image.LANCZOS) \
          if bg_path else Image.new("RGB",(THUMB_W,THUMB_H),(15,10,30))
    overlay = Image.new("RGBA",(THUMB_W,THUMB_H),(0,0,0,120))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    main_font = find_korean_font(int(THUMB_H*0.20))
    bbox  = draw.textbbox((0,0), phrase, font=main_font)
    tw,th = bbox[2]-bbox[0], bbox[3]-bbox[1]
    x,y   = (THUMB_W-tw)//2, (THUMB_H-th)//2-30
    draw.text((x+4,y+4), phrase, font=main_font, fill=(0,0,0))
    draw.text((x,y),     phrase, font=main_font, fill=(255,255,255))

    sub  = "JAPANESE CITY POP  ✦  LOFI"
    sf   = find_korean_font(int(THUMB_H*0.05))
    sb   = draw.textbbox((0,0), sub, font=sf)
    draw.text(((THUMB_W-(sb[2]-sb[0]))//2, y+th+20), sub, font=sf, fill=(200,162,200))

    wf = find_korean_font(int(THUMB_H*0.045))
    wb = draw.textbbox((0,0),"J_Jlaylist",font=wf)
    draw.text((THUMB_W-(wb[2]-wb[0])-30, THUMB_H-int(THUMB_H*0.045)-20),
              "J_Jlaylist", font=wf, fill=(180,180,180))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(str(output_path),"JPEG",quality=95)
    print(f"  ✓ {output_path.name}  ({mood} / '{phrase}')")
    return output_path

def get_youtube():
    creds = None
    if TOKEN_PATH.exists():
        with open(TOKEN_PATH,"rb") as f: creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token: creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET),SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_PATH,"wb") as f: pickle.dump(creds,f)
    return build("youtube","v3",credentials=creds)

def apply_thumbnail(youtube, video_id, thumb_path):
    try:
        youtube.thumbnails().set(videoId=video_id,
            media_body=MediaFileUpload(str(thumb_path),mimetype="image/jpeg")).execute()
        print(f"  🖼️  적용: {video_id}")
        return True
    except Exception as e:
        print(f"  [ERROR] {e}"); return False

def load_batch_log():
    if not BATCH_LOG.exists(): return {}
    with open(BATCH_LOG,"r",encoding="utf-8") as f: data = json.load(f)
    return {str(i):v for i,v in enumerate(data)} if isinstance(data,list) else data

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch",     type=int, default=None)
    parser.add_argument("--preview",   action="store_true")
    parser.add_argument("--apply",     action="store_true")
    parser.add_argument("--no-claude", action="store_true")
    args = parser.parse_args()

    print("="*60)
    print("  thumbnail_auto_v2.py  —  감성형 썸네일 생성")
    print("="*60)

    log = load_batch_log()
    if not log: print("[ERROR] batch_log.json 없음"); sys.exit(1)

    youtube = get_youtube() if args.apply else None
    targets = {str(args.batch): log[str(args.batch)]} if args.batch is not None else log
    if args.preview:
        k = next(iter(targets)); targets = {k: targets[k]}
        print("[PREVIEW] 1개만 생성\n")

    success, fail = [], []
    for i,(key,val) in enumerate(targets.items()):
        if not isinstance(val,dict): continue
        mix_title = val.get("mix_title", f"Mix #{key}")
        video_id  = val.get("video_id","")
        batch_num = int(key) if key.isdigit() else i
        mood      = MOOD_DIRS[batch_num % len(MOOD_DIRS)]
        print(f"\n[배치 {key}] {mix_title}")

        phrase = MOOD_PHRASES.get(mood,["도쿄의 밤"])[batch_num%3] if args.no_claude \
                 else generate_phrase(mix_title, mood)

        out = THUMB_OUT_DIR / f"thumb_v2_batch{key}.jpg"
        if make_thumbnail(batch_num, mix_title, phrase, out):
            log[key]["thumbnail_v2_path"] = str(out)
            success.append(key)
            if args.apply and video_id:
                apply_thumbnail(youtube, video_id, out)
                __import__("time").sleep(2)
        else:
            fail.append(key)

    if success:
        with open(BATCH_LOG,"w",encoding="utf-8") as f:
            json.dump(log,f,ensure_ascii=False,indent=2)

    print(f"\n{'='*60}\n  완료: {len(success)}개  /  실패: {len(fail)}개")
    print(f"  출력: {THUMB_OUT_DIR}\n{'='*60}")

if __name__ == "__main__":
    main()