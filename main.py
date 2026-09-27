import os
import io
import uuid
import base64
import textwrap
import threading
import requests
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

FONT_BOLD_PATH = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"
FONT_LIGHT_PATH = "/tmp/Montserrat-Light.ttf"

# In-memory image store: {uuid: bytes}
# Cleaned up after 10 minutes to avoid memory bloat
IMAGE_STORE: dict = {}
IMAGE_LOCK = threading.Lock()

# Brand colors
GOLD = (250, 168, 0)
WHITE = (255, 255, 255)
SHADOW = (0, 0, 10)

BASE_URL = os.environ.get("BASE_URL", "https://agentejuridico-img-service.onrender.com")


def ensure_fonts():
    fonts = [
        (FONT_BOLD_PATH, "Montserrat-Bold.ttf"),
        (FONT_REGULAR_PATH, "Montserrat-Regular.ttf"),
        (FONT_LIGHT_PATH, "Montserrat-Light.ttf"),
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
    with IMAGE_LOCK:
        IMAGE_STORE[image_id] = image_bytes
    # Schedule cleanup after 10 minutes
    def cleanup():
        import time
        time.sleep(600)
        with IMAGE_LOCK:
            IMAGE_STORE.pop(image_id, None)
    t = threading.Thread(target=cleanup, daemon=True)
    t.start()
    return f"{BASE_URL}/image/{image_id}"


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


def _clean_md(line: str) -> str:
    return line.replace("**", "").replace("__", "").strip()


def extract_headline(estrategista_output: str) -> str:
    lines = estrategista_output.split("\n")
    for i, raw_line in enumerate(lines):
        line = _clean_md(raw_line.strip())
        upper = line.upper()
        if upper.startswith("GANCHO DE ABERTURA:"):
            val = line[19:].strip().strip('"').strip("'")
            if val:
                return val
            for j in range(i + 1, min(i + 4, len(lines))):
                nxt = _clean_md(lines[j].strip()).strip('"').strip("'")
                if nxt and not nxt.upper().startswith("DESENVOLVIMENTO") and not nxt.upper().startswith("TOM:"):
                    return nxt
        elif upper.startswith("HEADLINE:"):
            val = line[9:].strip().strip('"')
            if val:
                return val
        elif upper.startswith("HOOK:"):
            val = line[5:].strip().strip('"')
            if val:
                return val
    for part in estrategista_output.split("|"):
        part = _clean_md(part.strip())
        upper = part.upper()
        if upper.startswith("HEADLINE:"):
            return part[9:].strip()
        if upper.startswith("HOOK:"):
            return part[5:].strip()
    return "Proteja sua marca"


def extract_tema(estrategista_output: str) -> str:
    for raw_line in estrategista_output.split("\n"):
        line = _clean_md(raw_line.strip())
        upper = line.upper()
        if upper.startswith("TÓPICO:") or upper.startswith("TOPICO:"):
            val = line[line.index(":") + 1:].strip()
            return val[:25].rstrip().upper() if len(val) > 25 else val.upper()
        if upper.startswith("FORMATO_DO_DIA:"):
            val = line[15:].strip()
            return val[:25].rstrip().upper() if len(val) > 25 else val.upper()
    for part in estrategista_output.split("|"):
        part = _clean_md(part.strip())
        upper = part.upper()
        if upper.startswith("TEMA:"):
            val = part[5:].strip()
            return val[:25].rstrip().upper() if len(val) > 25 else val.upper()
        if upper.startswith("TÓPICO:") or upper.startswith("TOPICO:"):
            val = part[part.index(":") + 1:].strip()
            return val[:25].rstrip().upper() if len(val) > 25 else val.upper()
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


class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


def _compose_image(req: ComposeRequest) -> dict:
    headline = extract_headline(req.estrategista_output)
    tema = extract_tema(req.estrategista_output)
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

    headline_top = draw_category_block(draw, tema, w, h)
    headline_upper = headline.upper()
    font, lines, line_h, text_top, text_bottom = fit_headline(draw, headline_upper, w, h, headline_top)
    draw_headline(draw, font, lines, line_h, text_top, text_bottom, w)
    draw_brand_handle(draw, req.brand_handle, w, h)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=94)
    composed_url = store_image(buf.getvalue())

    return {"composed_url": composed_url, "lines_rendered": lines, "headline": headline}


@app.get("/image/{image_id}")
def get_image(image_id: str):
    with IMAGE_LOCK:
        data = IMAGE_STORE.get(image_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Image not found or expired")
    return Response(content=data, media_type="image/jpeg")


@app.post("/compose")
def compose(req: ComposeRequest):
    return _compose_image(req)


@app.post("/compose/auto")
def compose_auto(req: ComposeRequest):
    return _compose_image(req)


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.11"}
