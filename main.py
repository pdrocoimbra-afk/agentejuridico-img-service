import os
import io
import time
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

# Brand colors — identidade visual @agentejuridico
ROYAL_BLUE = (16, 64, 200)    # #1040C8 — fundo principal
GOLD       = (250, 168, 0)    # #FAA800 — acento dourado
WHITE      = (255, 255, 255)
SHADOW     = (0, 0, 20)
MUTED      = (180, 180, 210)  # cinza-azulado para textos secundários
RED        = (210, 55, 55)    # alertas


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


def upload_imgbb(image_bytes: bytes, retries: int = 3) -> str:
    if not IMGBB_KEY:
        raise HTTPException(status_code=500, detail="IMGBB_KEY not configured")
    b64 = base64.b64encode(image_bytes).decode()
    last_error = None
    for attempt in range(retries):
        try:
            r = requests.post(
                "https://api.imgbb.com/1/upload",
                data={"key": IMGBB_KEY, "image": b64},
                timeout=40,
            )
            data = r.json()
            if data.get("success"):
                return data["data"]["url"]
            last_error = f"imgbb error: {data}"
        except Exception as e:
            last_error = str(e)
        if attempt < retries - 1:
            import time as t; t.sleep(2 ** attempt)
    raise HTTPException(status_code=500, detail=last_error)


def img_to_bytes(img, fmt="JPEG"):
    import io as _io
    buf = _io.BytesIO()
    if fmt == "PNG":
        img.save(buf, format="PNG", optimize=True)
    else:
        img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def apply_gradient_overlay(img):
    w, h = img.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    fade_start = int(h * 0.38)
    for y in range(fade_start, h):
        progress = (y - fade_start) / (h - fade_start)
        alpha = int(255 * (progress ** 1.3))
        draw.line([(0, y), (w - 1, y)], fill=(8, 32, 100, alpha))
    img_rgba = img.convert("RGBA")
    result = Image.alpha_composite(img_rgba, overlay)
    return result.convert("RGB")


def extract_headline(s):
    for part in s.split("|"):
        p = part.strip()
        if p.upper().startswith("HEADLINE:"):
            return p[9:].strip()
    for part in s.split("|"):
        p = part.strip()
        if p.upper().startswith("HOOK:"):
            return p[5:].strip()
    return "Proteja sua marca agora"


def extract_tema(s):
    for part in s.split("|"):
        p = part.strip()
        u = p.upper()
        if u.startswith("TEMA:"):
            return p[5:].strip()[:22].upper()
        if u.startswith("TOPICO:") or u.startswith("T\u00d3PICO:"):
            return p[p.index(":")+1:].strip()[:22].upper()
    return "PROPRIEDADE INTELECTUAL"


def draw_category_block(draw, tema, w, h):
    cx = w // 2
    bar_y = int(h * 0.525)
    bar_w = int(w * 0.12)
    draw.rectangle([cx - bar_w, bar_y, cx + bar_w, bar_y + 3], fill=GOLD)
    font = ImageFont.truetype(FONT_LIGHT_PATH, 22)
    label = "  ".join(tema) if len(tema) <= 14 else tema
    label_y = bar_y + 17
    draw.text((cx + 1, label_y + 1), label, font=font, fill=(0, 0, 0), anchor="mt")
    draw.text((cx, label_y), label, font=font, fill=GOLD, anchor="mt")
    return label_y + 36


def fit_headline(draw, headline, w, h, text_top):
    import textwrap as tw
    max_text_w = int(w * 0.86)
    text_bottom = int(h * 0.92)
    available_h = text_bottom - text_top
    for font_size in range(88, 28, -4):
        font = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        bbox = font.getbbox("W")
        char_w = (bbox[2] - bbox[0]) * 0.88
        chars_per_line = max(8, int(max_text_w / char_w))
        lines = tw.wrap(headline, width=chars_per_line)
        line_h = int(font_size * 1.20)
        if len(lines) * line_h <= available_h and len(lines) <= 4:
            return font, lines, line_h, text_top, text_bottom
    font = ImageFont.truetype(FONT_BOLD_PATH, 32)
    lines = tw.wrap(headline, width=20)[:4]
    return font, lines, 40, text_top, text_bottom


def draw_headline(draw, font, lines, line_h, text_top, text_bottom, w):
    total_text_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_text_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        draw.text((cx + 2, y + 3), line, font=font, fill=(*SHADOW, 220), anchor="mt")
        draw.text((cx + 1, y + 1), line, font=font, fill=(*SHADOW, 120), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw, handle, w, h):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 23)
    draw.text((w // 2, h - 20), handle, font=font, fill=(200, 200, 230), anchor="mb")


def centered(draw, text, y, font, color, w=1080):
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((w - tw) // 2, y), text, font=font, fill=color)
    return y + (bbox[3] - bbox[1]) + 10


def centered_wrap(draw, text, y, font, color, w=1080, max_chars=32):
    import textwrap as _tw
    for line in _tw.wrap(text, width=max_chars):
        y = centered(draw, line, y, font, color, w)
    return y


def gold_bar(draw, w=1080):
    draw.rectangle([(0, 0), (w, 7)], fill=GOLD)


def gold_accent_line(draw, y, w=1080, margin=90):
    draw.line([(margin, y), (w - margin, y)], fill=(*GOLD, 140), width=2)


def watermark(draw, w=1080, h=1080):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 26)
    draw.text((w // 2, h - 26), "@agentejuridico", font=font, fill=(*GOLD, 170), anchor="mb")


def background_with_noise(W, H):
    img = Image.new("RGB", (W, H), ROYAL_BLUE)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / H
        r = int(ROYAL_BLUE[0] * (1 - t * 0.25))
        g = int(ROYAL_BLUE[1] * (1 - t * 0.15))
        b = int(ROYAL_BLUE[2] * (1 - t * 0.08))
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    return img


def extract_field(text, field):
    for part in text.split("|"):
        p = part.strip()
        if p.upper().startswith(field.upper() + ":"):
            return p[len(field)+1:].strip()
    return ""


from fastapi import FastAPI
from pydantic import BaseModel


class ComposeRequest(BaseModel):
    image_url: str
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose")
def compose(req: ComposeRequest):
    headline = extract_headline(req.estrategista_output)
    tema = extract_tema(req.estrategista_output)
    ensure_fonts()
    resp = requests.get(req.image_url, timeout=30)
    resp.raise_for_status()
    img = Image.open(io.BytesIO(resp.content))
    w, h = img.size
    img = apply_gradient_overlay(img)
    draw = ImageDraw.Draw(img)
    headline_top = draw_category_block(draw, tema, w, h)
    headline = headline.upper()
    font, lines, line_h, text_top, text_bottom = fit_headline(draw, headline, w, h, headline_top)
    draw_headline(draw, font, lines, line_h, text_top, text_bottom, w)
    draw_brand_handle(draw, req.brand_handle, w, h)
    return {"composed_url": upload_imgbb(img_to_bytes(img)), "lines_rendered": lines}


class DadoRequest(BaseModel):
    numero: str
    unidade: str = ""
    descricao: str = ""
    cta: str = ""


@app.post("/compose/dado")
def compose_dado(req: DadoRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img = background_with_noise(W, H)
    draw = ImageDraw.Draw(img)
    gold_bar(draw, W)
    f_label = ImageFont.truetype(FONT_BOLD_PATH, 30)
    draw.text((W // 2, 48), "DADO DO DIA", font=f_label, fill=GOLD, anchor="mt")
    numero_txt = req.numero.upper()
    for font_size in [220, 180, 150, 120]:
        f_num = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        bbox = draw.textbbox((0, 0), numero_txt, font=f_num)
        if bbox[2] - bbox[0] < W * 0.88:
            break
    bbox = draw.textbbox((0, 0), numero_txt, font=f_num)
    num_w = bbox[2] - bbox[0]
    num_h = bbox[3] - bbox[1]
    num_x = (W - num_w) // 2
    num_y = 100
    for offset in [4, 2]:
        draw.text((num_x + offset, num_y + offset), numero_txt, font=f_num, fill=(*GOLD, 60))
    draw.text((num_x, num_y), numero_txt, font=f_num, fill=WHITE)
    y = num_y + num_h + 12
    if req.unidade:
        f_uni = ImageFont.truetype(FONT_REGULAR_PATH, 48)
        y = centered_wrap(draw, req.unidade.upper(), y, f_uni, GOLD, W, max_chars=28)
    gold_accent_line(draw, y + 20, W)
    y += 50
    if req.descricao:
        f_desc = ImageFont.truetype(FONT_REGULAR_PATH, 40)
        y = centered_wrap(draw, req.descricao, y, f_desc, WHITE, W, max_chars=36)
    if req.cta:
        y_cta = max(y + 44, H - 160)
        gold_accent_line(draw, y_cta - 18, W)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 36)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=40)
    watermark(draw, W, H)
    return {"composed_url": upload_imgbb(img_to_bytes(img, "PNG"))}


class AlertaRequest(BaseModel):
    mito: str
    verdade: str
    cta: str = ""


@app.post("/compose/alerta")
def compose_alerta(req: AlertaRequest):
    import textwrap as tw
    ensure_fonts()
    W, H = 1080, 1080
    img = background_with_noise(W, H)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(0, 0), (W, 7)], fill=RED)
    f_mito_title = ImageFont.truetype(FONT_BOLD_PATH, 100)
    draw.text((W // 2, 40), "MITO", font=f_mito_title, fill=RED, anchor="mt")
    cx = W // 2
    tri_y = 175
    tri_s = 68
    pts = [(cx, tri_y), (cx - tri_s, tri_y + int(tri_s * 1.7)), (cx + tri_s, tri_y + int(tri_s * 1.7))]
    draw.polygon(pts, fill=(80, 10, 10), outline=RED)
    draw.polygon(pts, outline=RED, width=3)
    f_exc = ImageFont.truetype(FONT_BOLD_PATH, 60)
    draw.text((cx, tri_y + 20), "!", font=f_exc, fill=WHITE, anchor="mt")
    y = tri_y + int(tri_s * 1.7) + 28
    box_pad = 28
    f_mt = ImageFont.truetype(FONT_REGULAR_PATH, 42)
    lines_m = tw.wrap(req.mito, width=28)
    box_h = len(lines_m) * 56 + box_pad * 2
    draw.rounded_rectangle([(50, y), (W - 50, y + box_h)], radius=14, fill=(40, 5, 5), outline=(140, 30, 30), width=2)
    y_m = y + box_pad
    for line in lines_m:
        bbox_m = draw.textbbox((0, 0), line, font=f_mt)
        lw = bbox_m[2] - bbox_m[0]
        lx = (W - lw) // 2
        draw.text((lx, y_m), line, font=f_mt, fill=(210, 80, 80))
        mid = y_m + f_mt.size // 2 + 2
        draw.line([(lx, mid), (lx + lw, mid)], fill=(210, 80, 80), width=2)
        y_m += 56
    y += box_h + 32
    gold_accent_line(draw, y, W)
    y += 28
    f_vl = ImageFont.truetype(FONT_BOLD_PATH, 46)
    y = centered(draw, "VERDADE:", y, f_vl, GOLD, W)
    y += 6
    f_vd = ImageFont.truetype(FONT_REGULAR_PATH, 42)
    y = centered_wrap(draw, req.verdade, y, f_vd, WHITE, W, max_chars=30)
    if req.cta:
        y_cta = max(y + 32, H - 150)
        gold_accent_line(draw, y_cta - 16, W)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 36)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=42)
    watermark(draw, W, H)
    return {"composed_url": upload_imgbb(img_to_bytes(img, "PNG"))}


class MemeRequest(BaseModel):
    setup: str
    reacao: str = "S\u00c9RIO MESMO?"
    punchline: str = ""
    cta: str = ""


@app.post("/compose/meme")
def compose_meme(req: MemeRequest):
    import textwrap as tw
    ensure_fonts()
    W, H = 1080, 1080
    img = background_with_noise(W, H)
    draw = ImageDraw.Draw(img)
    gold_bar(draw, W)
    f_sub = ImageFont.truetype(FONT_LIGHT_PATH, 28)
    draw.text((W // 2, 36), "@agentejuridico explica:", font=f_sub, fill=MUTED, anchor="mt")
    f_setup = ImageFont.truetype(FONT_REGULAR_PATH, 52)
    y = 108
    y = centered_wrap(draw, req.setup, y, f_setup, WHITE, W, max_chars=24)
    gold_accent_line(draw, y + 18, W)
    y += 50
    reacao_txt = req.reacao.upper()
    for font_size in [110, 90, 72, 58]:
        f_reac = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        lines_r = tw.wrap(reacao_txt, width=16)
        total_w = max(draw.textbbox((0, 0), line, font=f_reac)[2] for line in lines_r)
        if total_w < W * 0.90:
            break
    for line in lines_r:
        bbox_r = draw.textbbox((0, 0), line, font=f_reac)
        rw = bbox_r[2] - bbox_r[0]
        draw.text(((W - rw) // 2 + 3, y + 3), line, font=f_reac, fill=(*GOLD, 60))
        draw.text(((W - rw) // 2, y), line, font=f_reac, fill=GOLD)
        y += int(f_reac.size * 1.12)
    gold_accent_line(draw, y + 18, W)
    y += 44
    if req.punchline:
        f_punch = ImageFont.truetype(FONT_REGULAR_PATH, 46)
        y = centered_wrap(draw, req.punchline, y, f_punch, WHITE, W, max_chars=28)
    if req.cta:
        y_cta = max(y + 40, H - 150)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 38)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=40)
    watermark(draw, W, H)
    return {"composed_url": upload_imgbb(img_to_bytes(img, "PNG"))}


class AutoRequest(BaseModel):
    image_url: str = ""
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose/auto")
def compose_auto(req: AutoRequest):
    formato = extract_field(req.estrategista_output, "FORMATO").lower().strip()
    cta = extract_field(req.estrategista_output, "CTA")
    if formato == "dado":
        numero = extract_field(req.estrategista_output, "EXTRA1") or extract_field(req.estrategista_output, "NUMERO")
        unidade = extract_field(req.estrategista_output, "EXTRA2") or extract_field(req.estrategista_output, "UNIDADE")
        descricao = extract_field(req.estrategista_output, "EXTRA3") or extract_field(req.estrategista_output, "DESCRICAO")
        return compose_dado(DadoRequest(numero=numero, unidade=unidade, descricao=descricao, cta=cta))
    elif formato == "alerta":
        mito = extract_field(req.estrategista_output, "EXTRA1") or extract_field(req.estrategista_output, "MITO")
        verdade = extract_field(req.estrategista_output, "EXTRA2") or extract_field(req.estrategista_output, "VERDADE")
        return compose_alerta(AlertaRequest(mito=mito, verdade=verdade, cta=cta))
    elif formato == "meme":
        setup = extract_field(req.estrategista_output, "EXTRA1") or extract_field(req.estrategista_output, "SETUP")
        reacao = extract_field(req.estrategista_output, "EXTRA2") or "S\u00c9RIO MESMO?"
        punchline = extract_field(req.estrategista_output, "EXTRA3") or extract_field(req.estrategista_output, "PUNCHLINE")
        return compose_meme(MemeRequest(setup=setup, reacao=reacao, punchline=punchline, cta=cta))
    else:
        if not req.image_url:
            raise HTTPException(status_code=400, detail="image_url obrigat\u00f3rio para formato padrao")
        return compose(ComposeRequest(image_url=req.image_url, estrategista_output=req.estrategista_output, brand_handle=req.brand_handle))


@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0"}
