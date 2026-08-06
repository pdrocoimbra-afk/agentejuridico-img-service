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
FONT_BOLD_PATH    = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"
FONT_LIGHT_PATH   = "/tmp/Montserrat-Light.ttf"

GOLD   = (250, 168, 0)
WHITE  = (255, 255, 255)
SHADOW = (0, 0, 10)
MUTED  = (150, 150, 150)
BG     = (0, 10, 15)
RED    = (200, 60, 60)


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


def upload_imgbb(image_bytes: bytes) -> str:
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


def img_to_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=94)
    return buf.getvalue()


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
            return val[:25].rstrip().upper()
        if upper.startswith("TOPICO:"):
            val = part[part.index(":") + 1:].strip()
            return val[:25].rstrip().upper()
    return "DIREITO EMPRESARIAL"


def draw_category_block(draw, tema, w, h):
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


def fit_headline(draw, headline, w, h, text_top):
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


def draw_headline(draw, font, lines, line_h, text_top, text_bottom, w):
    total_text_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_text_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        draw.text((cx + 2, y + 3), line, font=font, fill=(*SHADOW, 200), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw, handle, w, h):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 22)
    draw.text((w // 2, h - 22), handle, font=font, fill=(180, 180, 180), anchor="mb")


def centered(draw, text, y, font, color, w=1080):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, y), text, font=font, fill=color)
    return y + (bbox[3] - bbox[1]) + 8


def centered_wrap(draw, text, y, font, color, w=1080, max_chars=32):
    lines = textwrap.wrap(text, width=max_chars)
    for line in lines:
        y = centered(draw, line, y, font, color, w)
    return y


def gold_bar(draw, w=1080):
    draw.rectangle([(0, 0), (w, 8)], fill=GOLD)


def divider(draw, y, w=1080, margin=80):
    draw.line([(margin, y), (w - margin, y)], fill=(*MUTED, 80), width=1)


def watermark(draw, w=1080, h=1080):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 26)
    draw.text((w // 2, h - 28), "@agentejuridico", font=font,
              fill=(*GOLD, 160), anchor="mb")


class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose")
def compose(req: ComposeRequest):
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
    headline = headline.upper()
    font, lines, line_h, text_top, text_bottom = fit_headline(draw, headline, w, h, headline_top)
    draw_headline(draw, font, lines, line_h, text_top, text_bottom, w)
    draw_brand_handle(draw, req.brand_handle, w, h)
    composed_url = upload_imgbb(img_to_bytes(img))
    return {"composed_url": composed_url, "lines_rendered": lines}


class DadoRequest(BaseModel):
    numero: str
    unidade: str = ""
    descricao: str = ""
    cta: str = ""


@app.post("/compose/dado")
def compose_dado(req: DadoRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    gold_bar(draw, W)
    f_label = ImageFont.truetype(FONT_BOLD_PATH, 28)
    draw.text((50, 34), "DADO DO DIA", font=f_label, fill=GOLD)
    f_num = ImageFont.truetype(FONT_BOLD_PATH, 200)
    bbox  = draw.textbbox((0, 0), req.numero, font=f_num)
    num_w = bbox[2] - bbox[0]
    num_h = bbox[3] - bbox[1]
    draw.text(((W - num_w) // 2, 160), req.numero, font=f_num, fill=WHITE)
    y = 160 + num_h + 16
    if req.unidade:
        f_uni = ImageFont.truetype(FONT_REGULAR_PATH, 52)
        y = centered(draw, req.unidade, y, f_uni, MUTED, W)
    divider(draw, y + 24, W)
    y += 60
    if req.descricao:
        f_desc = ImageFont.truetype(FONT_REGULAR_PATH, 42)
        y = centered_wrap(draw, req.descricao, y, f_desc, WHITE, W, max_chars=34)
    if req.cta:
        y_cta = max(y + 40, 900)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 38)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=38)
    watermark(draw, W, H)
    return {"composed_url": upload_imgbb(img_to_bytes(img))}


class AlertaRequest(BaseModel):
    mito: str
    verdade: str
    cta: str = ""


@app.post("/compose/alerta")
def compose_alerta(req: AlertaRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W, 8)], fill=RED)
    f_mito_title = ImageFont.truetype(FONT_BOLD_PATH, 96)
    bbox = draw.textbbox((0, 0), "MITO", font=f_mito_title)
    tw   = bbox[2] - bbox[0]
    draw.text(((W - tw) // 2, 52), "MITO", font=f_mito_title, fill=RED)
    cx, tri_top = W // 2, 192
    tri_s = 72
    draw.polygon(
        [(cx, tri_top), (cx - tri_s, tri_top + tri_s * 1.6), (cx + tri_s, tri_top + tri_s * 1.6)],
        fill=(160, 30, 30), outline=RED,
    )
    f_exc = ImageFont.truetype(FONT_BOLD_PATH, 56)
    draw.text((cx, tri_top + 28), "!", font=f_exc, fill=WHITE, anchor="mt")
    y = tri_top + int(tri_s * 1.6) + 32
    box_h = 160
    draw.rounded_rectangle([(60, y), (W - 60, y + box_h)],
                            radius=12, fill=(35, 5, 5), outline=(110, 25, 25), width=2)
    f_mt = ImageFont.truetype(FONT_REGULAR_PATH, 40)
    lines_m = textwrap.wrap(req.mito, width=30)
    y_m = y + (box_h - len(lines_m) * 52) // 2
    for line in lines_m:
        bbox_m = draw.textbbox((0, 0), line, font=f_mt)
        lw = bbox_m[2] - bbox_m[0]
        lx = (W - lw) // 2
        draw.text((lx, y_m), line, font=f_mt, fill=(200, 90, 90))
        mid = y_m + f_mt.size // 2
        draw.line([(lx, mid), (lx + lw, mid)], fill=(200, 90, 90), width=2)
        y_m += 52
    y += box_h + 40
    f_vl = ImageFont.truetype(FONT_BOLD_PATH, 44)
    y = centered(draw, "VERDADE:", y, f_vl, GOLD, W)
    y += 8
    f_vd = ImageFont.truetype(FONT_REGULAR_PATH, 42)
    y = centered_wrap(draw, req.verdade, y, f_vd, WHITE, W, max_chars=30)
    if req.cta:
        y_cta = max(y + 36, 900)
        divider(draw, y_cta - 20, W)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 36)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=40)
    watermark(draw, W, H)
    return {"composed_url": upload_imgbb(img_to_bytes(img))}


class MemeRequest(BaseModel):
    setup: str
    reacao: str = "SERIO MESMO?"
    punchline: str = ""
    cta: str = ""


@app.post("/compose/meme")
def compose_meme(req: MemeRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img  = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    gold_bar(draw, W)
    f_sub = ImageFont.truetype(FONT_LIGHT_PATH, 28)
    draw.text((50, 34), "@agentejuridico explica:", font=f_sub, fill=MUTED)
    f_setup = ImageFont.truetype(FONT_REGULAR_PATH, 50)
    y = 110
    y = centered_wrap(draw, req.setup, y, f_setup, WHITE, W, max_chars=26)
    divider(draw, y + 20, W)
    y += 56
    f_reac = ImageFont.truetype(FONT_BOLD_PATH, 104)
    lines_r = textwrap.wrap(req.reacao, width=16)
    for line in lines_r:
        bbox_r = draw.textbbox((0, 0), line, font=f_reac)
        rw = bbox_r[2] - bbox_r[0]
        draw.text(((W - rw) // 2, y), line, font=f_reac, fill=GOLD)
        y += int(f_reac.size * 1.15)
    divider(draw, y + 20, W)
    y += 50
    if req.punchline:
        f_punch = ImageFont.truetype(FONT_REGULAR_PATH, 46)
        y = centered_wrap(draw, req.punchline, y, f_punch, WHITE, W, max_chars=28)
    if req.cta:
        y_cta = max(y + 36, 900)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 38)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=38)
    watermark(draw, W, H)
    return {"composed_url": upload_imgbb(img_to_bytes(img))}


@app.get("/health")
def health():
    return {"status": "ok"}
