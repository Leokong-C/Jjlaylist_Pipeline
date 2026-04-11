from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import os
import re

def remove_emoji(text):
    return re.sub(r'[^\w\s가-힣ㄱ-ㅎㅏ-ㅣa-zA-Z0-9|·•\-,.]', '', text).strip()

def get_fit_font(draw, text, max_width, font_path, start_size=60):
    size = start_size
    while size > 18:
        try:
            font = ImageFont.truetype(font_path, size)
        except:
            return ImageFont.load_default(), size
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font, size
        size -= 3
    return ImageFont.load_default(), size

def create_thumbnail(title, output_path, bg_image_path=None, genre="citypop"):
    W, H = 1280, 720
    FONT_PATH = "C:/Windows/Fonts/malgun.ttf"

    if bg_image_path and os.path.exists(bg_image_path):
        img = Image.open(bg_image_path).resize((W, H))
    else:
        color = (20, 10, 40) if genre == "citypop" else (15, 20, 35)
        img = Image.new("RGB", (W, H), color)

    overlay = Image.new("RGBA", (W, H), (0, 0, 10, 150))
    img = img.convert("RGBA")
    img = Image.alpha_composite(img, overlay)
    img = img.convert("RGB")
    draw = ImageDraw.Draw(img)

    if genre == "citypop":
        accent_color = (255, 107, 157)
        sub_color = (180, 140, 255)
    else:
        accent_color = (100, 200, 255)
        sub_color = (150, 255, 200)

    draw.rectangle([0, 0, W, 6], fill=accent_color)
    draw.rectangle([0, H-6, W, H], fill=sub_color)

    clean_title = remove_emoji(title)
    MAX_W = W - 100

    font_main, _ = get_fit_font(draw, clean_title, MAX_W, FONT_PATH, start_size=64)
    try:
        font_sub = ImageFont.truetype(FONT_PATH, 34)
        font_tag = ImageFont.truetype(FONT_PATH, 26)
    except:
        font_sub = ImageFont.load_default()
        font_tag = font_sub

    bbox = draw.textbbox((0, 0), clean_title, font=font_main)
    text_w = bbox[2] - bbox[0]
    x = max(50, (W - text_w) // 2)

    draw.text((x+3, 293), clean_title, font=font_main, fill=(0, 0, 0))
    draw.text((x, 290), clean_title, font=font_main, fill=accent_color)

    sub = "1 HOUR MIX"
    bbox2 = draw.textbbox((0, 0), sub, font=font_sub)
    sub_w = bbox2[2] - bbox2[0]
    draw.text(((W - sub_w)//2, 375), sub, font=font_sub, fill=sub_color)

    draw.rectangle([0, H-55, W, H], fill=(0, 0, 0))
    draw.text((30, H-40), "J_Jlaylist", font=font_tag, fill=(200, 200, 200))

    tag = "#citypop #lofi" if genre == "citypop" else "#lofi #chillbeats"
    bbox3 = draw.textbbox((0, 0), tag, font=font_tag)
    tag_w = bbox3[2] - bbox3[0]
    draw.text((W - tag_w - 30, H-40), tag, font=font_tag, fill=sub_color)

    img.save(output_path, "PNG")
    print(f"썸네일 생성: {Path(output_path).name}")
    return output_path

def batch_create_thumbnails(metadata_list, output_folder="assets/thumbnails/auto/"):
    os.makedirs(output_folder, exist_ok=True)
    bg_images = list(Path("assets/thumbnails/").glob("*.jpg")) + \
                list(Path("assets/thumbnails/").glob("*.png"))

    for i, meta in enumerate(metadata_list):
        title = meta.get("title_ko", "J_Jlaylist")
        genre = "citypop" if any(k in title for k in ["시티팝", "citypop", "City Pop"]) else "lofi"
        bg = str(bg_images[i % len(bg_images)]) if bg_images else None
        output = f"{output_folder}thumb_{i+1:03d}.png"
        create_thumbnail(title=title, output_path=output, bg_image_path=bg, genre=genre)

    print(f"총 {len(metadata_list)}개 썸네일 생성 완료")

if __name__ == "__main__":
    import json
    with open("metadata_output.json", "r", encoding="utf-8") as f:
        metadata_list = json.load(f)
    batch_create_thumbnails(metadata_list)