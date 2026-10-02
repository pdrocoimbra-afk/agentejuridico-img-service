import os
import io
import base64
import re
import textwrap
import uuid
import time
from typing import Optional
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

VERSION = "2.13"

IMGBB_KEY = os.environ.get("IMGBB_KEY", "")
FONT_BOLD_PATH    = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"
FONT_LIGHT_PATH   = "/tmp/Montserrat-Light.ttf"

# Brand colors
GOLD   = (250, 168, 0)
WHITE  = (255, 255, 255)
SHADOW = (0, 0, 10)

# ---------------------------------------------------------------------------
# In-memory fallback store (used only if imgbb is unavailable)
# ---------------------------------------------------------------------------
_image_store: dict = {}
_IMAGE_TTL = 3600  # 1 hour


def _store_image(image_bytes: bytes) -> str:
    uid = str(uuid.uuid4())
    _image_store[uid] = {"data": image_bytes, "expires": time.time() + _IMAGE_TTL}
    # prune expired
    expired = [k for k, v in _image_store.items() if v["expires"] < time.time()]
    for k in expired:
        _image_store.pop(k, None)
    return uid


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------
def _normalize(text: str) -> str:
    return text.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def _clean_md(text: str) -> str:
    return re.sub(r"[*_`#]", "", text).strip()


_SKIP_RE = re.compile(
    r"^(TEMA|TOPICO|TOP[IÍ]CO|FORMATO|ASSUNTO|[AÁ]REA|PLATAFORMA|"
    r"COPYWRITER|ESTRATEGISTA|CONTEUDO|CONTE[UÚ]DO|CTA|HASHTAG|"
    r"CONCLUS[AÃ]O|ABERTURA|GANCHO|HOOK|HEADLINE|HOOK\s+DE)[\s:–\-|]",
    re.IGNORECASE,
)

_HEADLINE_KW = re.compile(
    r"^(GANCHO\s+DE\s+ABERTURA|HEADLINE|HOOK|GANCHO|ABERTURA)\s*[:\-–|]\s*(.+)",
    re.IGNORECASE,
)


def extract_headline(raw: str) -> str:
    text = _normalize(raw)

    # Strategy 1 — keyword on its own line
    for line in text.splitlines():
        line = _clean_md(line).strip()
        m = _HEADLINE_KW.match(line)
        if m:
            val = _clean_md(m.group(2)).strip()
            if len(val) >= 10:
                return val

    # Strategy 2 — pipe-separated
    for part in text.split("|"):
        part = _clean_md(part).strip()
        m = _HEADLINE_KW.match(part)
        if m:
            val = _clean_md(m.group(2)).strip()
            if len(val) >= 10:
                return val

    # Strategy 3 — first content-rich line (>=20 chars, not a label line)
    for line in text.splitlines():
        line = _clean_md(line).strip()
        if len(line) >= 20 and not _SKIP_RE.match(line):
            return line

    return "Proteja sua marca agora"


def extract_tema(raw: str) -> str:
    text = _normalize(raw)
    pattern = re.compile(
        r"^(TEMA|TOPICO|TOP[IÍ]CO|ASSUNTO|[AÁ]REA)\s*[:\-–|]\s*(.+)",
        re.IGNORECASE,
    )
    for segment in text.splitlines() + text.split("|"):
        part = _clean_md(segment).strip()
        m = pattern.match(part)
        if m:
            val = _clean_md(m.group(2)).strip()
            return val[:25].upper() if val else "DIREITO EMPRESARIAL"
    return "DIREITO EMPRESARIAL"


# ---------------------------------------------------------------------------
# Image utilities
# ---------------------------------------------------------------------------
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


def upload_image(image_bytes: bytes) -> str:
    """Upload to imgbb (permanent URL). Falls back to in-memory store."""
    if IMGBB_KEY:
        b64 = base64.b64encode(image_bytes).decode()
        r = requests.post(
            "https://api.imgbb.com/1/upload",
            data={"key": IMGBB_KEY, "image": b64},
            timeout=30,
        )
        data = r.json()
        if data.get("success"):
            return data["data"]["url"]

    # Fallback: in-memory (only reliable within same request chain)
    uid = _store_image(image_bytes)
    base_url = os.environ.get("RENDER_EXTERNAL_URL", "https://agentejuridico-img-service.onrender.com")
    return f"{base_url}/image/{uid}"


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
    return Image.alpha_composite(img_rgba, overlay).convert("RGB")


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


def fit_headline(draw, headline: str, w: int, h: int, text_top: int):
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
        if len(lines) * line_h <= available_h and len(lines) <= 4:
            return font, lines, line_h, text_top, text_bottom
    font = ImageFont.truetype(FONT_BOLD_PATH, 30)
    lines = textwrap.wrap(headline, width=22)[:4]
    return font, lines, 38, text_top, text_bottom


def draw_headline(draw, font, lines, line_h, text_top, text_bottom, w):
    total_text_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_text_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        draw.text((cx + 2, y + 3), line, font=font, fill=(*SHADOW, 200), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw, handle: str, w: int, h: int):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 22)
    draw.text((w // 2, h - 22), handle, font=font, fill=(180, 180, 180), anchor="mb")


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------
class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"
    headline: Optional[str] = None
    tema: Optional[str] = None


# ---------------------------------------------------------------------------
# Core compose logic
# ---------------------------------------------------------------------------
def _compose_image(req: ComposeRequest) -> dict:
    headline = req.headline or extract_headline(req.estrategista_output)
    tema = req.tema or extract_tema(req.estrategista_output)
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
    composed_url = upload_image(buf.getvalue())

    return {
        "composed_url": composed_url,
        "headline_used": headline,
        "tema_used": tema,
        "lines_rendered": lines,
        "version": VERSION,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.post("/compose/auto")
def compose_auto(req: ComposeRequest):
    return _compose_image(req)


@app.post("/compose")
def compose(req: ComposeRequest):
    return _compose_image(req)


@app.get("/image/{uid}")
def serve_image(uid: str):
    from fastapi.responses import Response
    entry = _image_store.get(uid)
    if not entry or entry["expires"] < time.time():
        raise HTTPException(status_code=404, detail="Image expired or not found")
    return Response(content=entry["data"], media_type="image/jpeg")


@app.post("/debug/extract")
def debug_extract(req: ComposeRequest):
    return {
        "headline": extract_headline(req.estrategista_output),
        "tema": extract_tema(req.estrategista_output),
        "input_length": len(req.estrategista_output),
        "input_preview": req.estrategista_output[:500],
        "version": VERSION,
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": VERSION, "imgbb_configured": bool(IMGBB_KEY)}
