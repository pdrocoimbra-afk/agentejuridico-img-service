import os
import io
import base64
import textwrap
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

IMGBB_KEY = os.environ.get("IMGBB_KEY", ""
FONT_BOLD_PATH = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"

GOLD = (250, 168, 0)
WHITE = (255, 255, 255)
SHADOW = (0, 0, 10)


def ensure_fonts():
    if not os.path.exists(FONT_BOLD_PATH):
        r = requests.get("https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Bold.ttf", timeout=30)
        r.raise_for_status()
        open(FONT_BOLD_PATH, "wb").write(r.content)
    if not os.path.exists(FONT_REGULAR_PATH):
        r = requests.get("https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/Montserrat-Regular.ttf", timeout=30)
        r.raise_for_status()
        open(FONT_REGULAR_PATH, "wb").write(r.content)


def upload_imgbb(image_bytes):
    if not IMGBB_KEY:
        raise HTTPException(status_code=500, detail="IMGBB_KEY not configured")
    b64 = base64.b64encode(image_bytes).decode()
    r = requests.post("https://api.imgbb.com/1/upload", data={"key": IMGBB_KEY, "image": b64}, timeout=30)
    data = r.json()
    if not data.get("success"):
        raise HTTPException(status_code=500, detail=f"imgbb error: {data}")
    return data["data"]["url"]


def apply_gradient_overlay(img):
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        fade_start = int(h * 0.20)  # gradient starts earlier (20% from top)
    for y in range(fade_start, h):
        progress = (y - fade_start) / (h - fade_start)
                # Steeper curve: bottom 50% is nearly pitch black
                        alpha = int(255 * (progress ** 0.5))
                draw.line([(0, y), (w - 1, y)], fill=(0, 3, 15, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def draw_gold_accent_line(draw, w, h):
    y = int(h * 0.53)
    draw.rectangle([int(w * 0.06), y, int(w * 0.94), y + 4], fill=GOLD)


def fit_headline(draw, headline, w, h):
    max_text_w = int(w * 0.86)
    text_top = int(h * 0.56)
    text_bottom = int(h * 0.91)
    available_h = text_bottom - text_top
    for font_size in range(92, 26, -3):
        font = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        bbox = font.getbbox("W")
        char_w = (bbox[2] - bbox[0]) * 0.92
        chars_per_line = max(8, int(max_text_w / char_w))
        lines = textwrap.wrap(headline, width=chars_per_line)
        line_h = int(font_size * 1.25)
        if len(lines) * line_h <= available_h and len(lines) <= 4:
            return font, lines, line_h, text_top, text_bottom
    font = ImageFont.truetype(FONT_BOLD_PATH, 32)
    return font, textwrap.wrap(headline, width=22)[:4], 40, text_top, text_bottom


def draw_headline(draw, font, lines, line_h, text_top, text_bottom, w):
    total_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        draw.text((cx + 2, y + 3), line, font=font, fill=(*SHADOW, 180), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw, handle, w, h):
    font = ImageFont.truetype(FONT_REGULAR_PATH, 26)
    draw.text((w - 28, h - 28), handle, font=font, fill=(210, 210, 210), anchor="rb")


def extract_headline(text):
    for part in text.split("|"):
        part = part.strip()
        if part.upper().startswith("HEADLINE:"):
            return part[9:].strip()
    for part in text.split("|"):
        part = part.strip()
        if part.upper().startswith("HOOK:"):
            return part[5:].strip()
    return "Proteja sua marca agora"


class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose")
def compose(req: ComposeRequest):
    headline = extract_headline(req.estrategista_output)
    ensure_fonts()
    try:
        resp = requests.get(req.image_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download image: {e}")
    img = Image.open(io.BytesIO(resp.content))
    w, h = img.size
    img = apply_gradient_overlay(img)
    draw = ImageDraw.Draw(img)
    draw_gold_accent_line(draw, w, h)
    font, lines, line_h, text_top, text_bottom = fit_headline(draw, headline.upper(), w, h)
    draw_headline(draw, font, lines, line_h, text_top, text_bottom, w)
    draw_brand_handle(draw, req.brand_handle, w, h)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=94)
    return {"composed_url": upload_imgbb(buf.getvalue()), "lines_rendered": lines}


@app.get("/health")
def health():
    return {"status": "ok"}
