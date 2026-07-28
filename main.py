import os
import io
import base64
import textwrap
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

IMGBB_KEY = os.environ.get("IMGBB_KEY", "")
FONT_BOLD_PATH = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"
FONT_LIGHT_PATH = "/tmp/Montserrat-Light.ttf"

# Brand colors
GOLD = (250, 168, 0)        # #FAA800
WHITE = (255, 255, 255)
SHADOW = (0, 0, 10)


def ensure_fonts():
    """Download Montserrat fonts if not cached."""
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


def upload_imgbb(image_bytes: bytes) -> str:
    """Upload image bytes to imgbb and return public URL."""
    if not IMGBB_KEY:
        raise HTTPException(status_code=500, detail="IMGBB_KEY not configured")
    b64 = base64.b64encode(image_bytes).decode()
    r = requests.post(
        "https://api.imgbb.com/1/upload",
        data={"key": IMGBB_KEY, "image": b64},
        timeout=30,
    )
    data = r.json()
    if not data.get("success"):
        raise HTTPException(status_code=500, detail=f"imgbb error: {data}")
    return data["data"]["url"]


def apply_gradient_overlay(img: Image.Image) -> Image.Image:
    """Apply dark overlay — starts at 40% from top with smooth easing."""
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
    """Extract HEADLINE field from pipe-separated Estrategista output."""
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
    """Extract TEMA or TOPICO field from pipe-separated Estrategista output."""
    for part in estrategista_output.split("|"):
        part = part.strip()
        upper = part.upper()
        if upper.startswith("TEMA:"):
            val = part[5:].strip()
            if len(val) > 25:
                val = val[:25].rstrip()
            return val.upper()
        if upper.startswith("TÓPICO:") or upper.startswith("TOPICO:"):
            val = part[part.index(":") + 1:].strip()
            if len(val) > 25:
                val = val[:25].rstrip()
            return val.upper()
    return "DIREITO EMPRESARIAL"


def draw_category_block(draw: ImageDraw.Draw, tema: str, w: int, h: int) -> int:
    """
    Draw a short gold accent line + spaced category label.
    Returns the y where the headline area should begin.
    """
    cx = w // 2

    # Short gold bar — thin and centered, anchored visually above the label
    bar_y = int(h * 0.535)
    bar_half_w = int(w * 0.055)
    draw.rectangle(
        [cx - bar_half_w, bar_y, cx + bar_half_w, bar_y + 3],
        fill=GOLD,
    )

    # Spaced-caps category label in gold
    font = ImageFont.truetype(FONT_LIGHT_PATH, 20)
    spaced = "  ".join(tema)   # simulate letter-spacing
    label_y = bar_y + 3 + 12
    # Subtle shadow
    draw.text((cx + 1, label_y + 1), spaced, font=font,
              fill=(0, 0, 0), anchor="mt")
    draw.text((cx, label_y), spaced, font=font, fill=GOLD, anchor="mt")

    return label_y + 34  # headline starts here


def fit_headline(draw: ImageDraw.Draw, headline: str, w: int, h: int,
                 text_top: int) -> tuple:
    """Find the largest font size where headline fits in the text area."""
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
    """Draw centered headline with drop shadow."""
    total_text_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_text_h) // 2

    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        draw.text((cx + 2, y + 3), line, font=font,
                  fill=(*SHADOW, 200), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw: ImageDraw.Draw, handle: str, w: int, h: int):
    """Draw brand handle — bottom center, subtle."""
    font = ImageFont.truetype(FONT_LIGHT_PATH, 22)
    draw.text((w // 2, h - 22), handle, font=font,
              fill=(180, 180, 180), anchor="mb")


class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose")
def compose(req: ComposeRequest):
    headline = extract_headline(req.estrategista_output)
    tema = extract_tema(req.estrategista_output)
    ensure_fonts()

    # 1. Download Ideogram background
    try:
        resp = requests.get(req.image_url, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to download image: {e}")

    img = Image.open(io.BytesIO(resp.content))
    w, h = img.size

    # 2. Dark gradient overlay
    img = apply_gradient_overlay(img)
    draw = ImageDraw.Draw(img)

    # 3. Category block: short gold bar + spaced label
    headline_top = draw_category_block(draw, tema, w, h)

    # 4. Headline (uppercase bold)
    headline = headline.upper()
    font, lines, line_h, text_top, text_bottom = fit_headline(
        draw, headline, w, h, headline_top
    )
    draw_headline(draw, font, lines, line_h, text_top, text_bottom, w)

    # 5. Brand handle (bottom center)
    draw_brand_handle(draw, req.brand_handle, w, h)

    # 6. Export and upload
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=94)
    composed_url = upload_imgbb(buf.getvalue())

    return {"composed_url": composed_url, "lines_rendered": lines}


@app.get("/health")
def health():
    return {"status": "ok"}
