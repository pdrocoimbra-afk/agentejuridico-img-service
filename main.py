import os
import io
import uuid
import base64
import textwrap
import requests
from fastapi import FastAPI, HTTPException, Form
from fastapi.responses import Response
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

# In-memory image store — serves images without 3rd-party CDN
IMAGE_STORE: dict = {}

RENDER_URL = os.environ.get(
    "RENDER_EXTERNAL_URL", "https://agentejuridico-img-service.onrender.com"
)
IMGBB_KEY = os.environ.get("IMGBB_KEY", "")
FONT_BOLD_PATH = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"
FONT_LIGHT_PATH = "/tmp/Montserrat-Light.ttf"

GOLD = (250, 168, 0)
WHITE = (255, 255, 255)
SHADOW = (0, 0, 10)


def ensure_fonts():
    fonts = [
        (FONT_BOLD_PATH,    "Montserrat-Bold.ttf"),
        (FONT_REGULAR_PATH, "Montserrat-Regular.ttf"),
        (FONT_LIGHT_PATH,   "Montserrat-Light.ttf"),
    ]
    base = "https://github.com/JulietaUla/Montserrat/raw/master/fonts/ttf/"
    for path, filename in fonts:
        if not os.path.exists(path):
            r = requests.get(base + filename, timeout=30)
            r.raise_for_status()
            with open(path, "wb") as f:
                f.write(r.content)


def store_image(image_bytes: bytes) -> str:
    image_id = str(uuid.uuid4())
    IMAGE_STORE[image_id] = image_bytes
    if len(IMAGE_STORE) > 20:
        oldest_key = next(iter(IMAGE_STORE))
        del IMAGE_STORE[oldest_key]
    return f"{RENDER_URL}/img/{image_id}"


@app.get("/img/{image_id}")
def serve_image(image_id: str):
    if image_id not in IMAGE_STORE:
        raise HTTPException(status_code=404, detail="Image not found or expired")
    return Response(content=IMAGE_STORE[image_id], media_type="image/jpeg")


def apply_gradient_overlay(img: Image.Image) -> Image.Image:
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fade_start = int(h * 0.40)
    for y in range(fade_start, h):
        progress = (y - fade_start) / (h - fade_start)
        alpha = int(255 * (progress ** 1.5))
        draw.line([(0, y), (w - 1, y)], fill=(0, 3, 15, alpha))
    img_rgba = img.convert("RGBA")
    result = Image.alpha_composite(img_rgba, overlay)
    return result.convert("RGB")


def extract_headline(estrategista_output: str) -> str:
    for part in estrategista_output.split("|"):
        part = part.strip()
        if part.upper().startswith("HEADLINE:"):
            return part[9:].strip()
    for part in estrategista_output.split("|"):
        part = part.strip()
        if part.upper().startswith("HOOK:"):
            return part[5:].strip()
    return "Proteja sua marca agora"


def extract_tema(estrategista_output: str) -> str:
    for part in estrategista_output.split("|"):
        part = part.strip()
        upper = part.upper()
        if upper.startswith("TEMA:"):
            val = part[5:].strip()
            if len(val) > 25:
                val = val[:25].rstrip()
            return val.upper()
        if upper.startswith("TOPICO:"):
            val = part[part.index(":") + 1:].strip()
            if len(val) > 25:
                val = val[:25].rstrip()
            return val.upper()
    return "DIREITO EMPRESARIAL"


def draw_category_block(draw: ImageDraw.Draw, tema: str, w: int, h: int) -> int:
    cx = w // 2
    bar_y = int(h * 0.535)
    bar_half_w = int(w * 0.055)
    draw.rectangle([cx - bar_half_w, bar_y, cx + bar_half_w, bar_y + 3], fill=GOLD)
    font = ImageFont.truetype(FONT_LIGHT_PATH, 20)
    spaced = "  ".join(tema)
    label_y = bar_y + 3 + 12
    draw.text((cx + 1, label_y + 1), spaced, font=font, fill=(0, 0, 0), anchor="mt")
    draw.text((cx, label_y), spaced, font=font, fill=GOLD, anchor="mt")
    return label_y + 34


def fit_headline(draw: ImageDraw.Draw, headline: str, w: int, h: int, text_top: int) -> tuple:
    max_text_w = int(w * 0.84)
    text_bottom = int(h * 0.91)
    available_h = text_bottom - text_top
    for font_size in range(90, 26, -3):
        font = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        bbox = font.getbbox("W")
        char_w = (bbox[2] - bbox[0]) * 0.90
        chars_per_line = max(8, int(max_text_w / char_w))
        lines = textwrap.wrap(headline, width=chars_per_line)
        line_h = int(font_size * 1.22)
        total_h = len(lines) * line_h
        if total_h <= available_h and len(lines) <= 4:
            return font, lines, line_h, text_top, text_bottom
    font = ImageFont.truetype(FONT_BOLD_PATH, 30)
    lines = textwrap.wrap(headline, width=22)[:4]
    return font, lines, 38, text_top, text_bottom


def draw_headline(draw: ImageDraw.Draw, font, lines: list, line_h: int,
                  text_top: int, text_bottom: int, w: int):
    total_text_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_text_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        draw.text((cx + 2, y + 3), line, font=font, fill=(*SHADOW, 200), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw: ImageDraw.Draw, handle: str, w: int, h: int):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 22)
    draw.text((w // 2, h - 22), handle, font=font, fill=(180, 180, 180), anchor="mb")


def _compose_image(image_url: str, estrategista_output: str, brand_handle: str) -> bytes:
    headline = extract_headline(estrategista_output)
    tema = extract_tema(estrategista_output)
    ensure_fonts()
    try:
        resp = requests.get(image_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download image: {e}")
    img = Image.open(io.BytesIO(resp.content))
    w, h = img.size
    img = apply_gradient_overlay(img)
    draw = ImageDraw.Draw(img)
    headline_top = draw_category_block(draw, tema, w, h)
    headline = headline.upper()
    font, lines, line_h, text_top, text_bottom = fit_headline(draw, headline, w, h, headline_top)
    draw_headline(draw, font, lines, line_h, text_top, text_bottom, w)
    draw_brand_handle(draw, brand_handle, w, h)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=94)
    return buf.getvalue()


class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose")
def compose(req: ComposeRequest):
    image_bytes = _compose_image(req.image_url, req.estrategista_output, req.brand_handle)
    composed_url = store_image(image_bytes)
    return {"composed_url": composed_url, "status": "ok"}


@app.post("/compose/auto")
def compose_auto(
    image_url: str = Form(...),
    estrategista_output: str = Form(...),
    brand_handle: str = Form("@agentejuridico"),
):
    image_bytes = _compose_image(image_url, estrategista_output, brand_handle)
    composed_url = store_image(image_bytes)
    return {"composed_url": composed_url, "status": "ok"}


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.6"}
