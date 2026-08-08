import os
import io
import uuid
import random
import textwrap
import requests
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont

app = FastAPI()

FONT_BOLD_PATH    = "/tmp/Montserrat-Bold.ttf"
FONT_REGULAR_PATH = "/tmp/Montserrat-Regular.ttf"
FONT_LIGHT_PATH   = "/tmp/Montserrat-Light.ttf"

# Self-hosted image storage — sem dependência de ImgBB
IMAGE_DIR = Path("/tmp/aj_images")
IMAGE_DIR.mkdir(exist_ok=True)
BASE_URL = os.environ.get("SERVICE_BASE_URL", "https://agentejuridico-img-service.onrender.com")

# Brand colors — identidade visual @agentejuridico
ROYAL_BLUE = (16, 64, 200)    # #1040C8 — fundo principal
GOLD       = (250, 168, 0)    # #FAA800 — acento dourado
WHITE      = (255, 255, 255)
SHADOW     = (0, 0, 20)
MUTED      = (180, 180, 210)  # cinza-azulado para textos secundários
RED        = (210, 55, 55)    # alertas


# ── Utilitários ──────────────────────────────────────────────────────────────

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


def host_image(image_bytes: bytes, fmt: str = "JPEG") -> str:
    """Salva imagem em /tmp e retorna URL pública do próprio serviço."""
    ext = "png" if fmt == "PNG" else "jpg"
    filename = f"{uuid.uuid4().hex[:12]}.{ext}"
    filepath = IMAGE_DIR / filename
    filepath.write_bytes(image_bytes)
    return f"{BASE_URL}/image/{filename}"


def img_to_bytes(img: Image.Image, fmt: str = "JPEG") -> bytes:
    buf = io.BytesIO()
    if fmt == "PNG":
        img.save(buf, format="PNG", optimize=True)
    else:
        img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def apply_gradient_overlay(img: Image.Image) -> Image.Image:
    """Degradê suave de azul-royal escuro cobrindo a metade inferior da imagem."""
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
    """Extrai o tópico do dia para exibir como label na imagem (máx 22 chars)."""
    for part in estrategista_output.split("|"):
        part = part.strip()
        upper = part.upper()
        if upper.startswith("TEMA:"):
            val = part[5:].strip()
            return val[:22].rstrip().upper()
        if upper.startswith("TOPICO:") or upper.startswith("TÓPICO:"):
            val = part[part.index(":") + 1:].strip()
            return val[:22].rstrip().upper()
    return "PROPRIEDADE INTELECTUAL"


def draw_category_block(draw, tema, w, h):
    """Barra dourada + label do tópico no ponto de transição do degradê."""
    cx = w // 2
    bar_y = int(h * 0.525)
    bar_w = int(w * 0.12)
    draw.rectangle([cx - bar_w, bar_y, cx + bar_w, bar_y + 3], fill=GOLD)

    font = ImageFont.truetype(FONT_LIGHT_PATH, 22)
    # Letra-espaçada apenas se o tema for curto (≤ 14 chars)
    label = "  ".join(tema) if len(tema) <= 14 else tema
    label_y = bar_y + 3 + 14
    # Sombra
    draw.text((cx + 1, label_y + 1), label, font=font, fill=(0, 0, 0), anchor="mt")
    draw.text((cx, label_y), label, font=font, fill=GOLD, anchor="mt")
    return label_y + 36


def fit_headline(draw, headline, w, h, text_top):
    max_text_w = int(w * 0.86)
    text_bottom = int(h * 0.92)
    available_h = text_bottom - text_top
    for font_size in range(88, 28, -4):
        font = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        bbox = font.getbbox("W")
        char_w = (bbox[2] - bbox[0]) * 0.88
        chars_per_line = max(8, int(max_text_w / char_w))
        lines = textwrap.wrap(headline, width=chars_per_line)
        line_h = int(font_size * 1.20)
        total_h = len(lines) * line_h
        if total_h <= available_h and len(lines) <= 4:
            return font, lines, line_h, text_top, text_bottom
    font = ImageFont.truetype(FONT_BOLD_PATH, 32)
    lines = textwrap.wrap(headline, width=20)[:4]
    return font, lines, 40, text_top, text_bottom


def draw_headline(draw, font, lines, line_h, text_top, text_bottom, w):
    total_text_h = len(lines) * line_h
    start_y = text_top + (text_bottom - text_top - total_text_h) // 2
    for i, line in enumerate(lines):
        y = start_y + i * line_h
        cx = w // 2
        # Sombra dupla para leitura sobre qualquer imagem
        draw.text((cx + 2, y + 3), line, font=font, fill=(*SHADOW, 220), anchor="mt")
        draw.text((cx + 1, y + 1), line, font=font, fill=(*SHADOW, 120), anchor="mt")
        draw.text((cx, y), line, font=font, fill=WHITE, anchor="mt")


def draw_brand_handle(draw, handle, w, h):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 23)
    draw.text((w // 2, h - 20), handle, font=font, fill=(200, 200, 230), anchor="mb")


def centered(draw, text, y, font, color, w=1080):
    """Desenha texto centralizado. Usa anchor='lt' para comportamento
    consistente entre versões do Pillow — y é sempre o TOPO do texto."""
    bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
    tw = bbox[2] - bbox[0]
    x = (w - tw) // 2
    draw.text((x, y), text, font=font, fill=color, anchor="lt")
    # Retorna posição absoluta do fundo do texto + espaçamento
    abs_bottom = draw.textbbox((x, y), text, font=font, anchor="lt")[3]
    return abs_bottom + 10


def centered_wrap(draw, text, y, font, color, w=1080, max_chars=32):
    lines = textwrap.wrap(text, width=max_chars)
    for line in lines:
        y = centered(draw, line, y, font, color, w)
    return y


def gold_bar(draw, w=1080):
    draw.rectangle([(0, 0), (w, 7)], fill=GOLD)


def gold_accent_line(draw, y, w=1080, margin=90):
    """Linha dourada fina como divisor de seção."""
    draw.line([(margin, y), (w - margin, y)], fill=(*GOLD, 140), width=2)


def divider(draw, y, w=1080, margin=80):
    draw.line([(margin, y), (w - margin, y)], fill=(*MUTED, 60), width=1)


def watermark(draw, w=1080, h=1080):
    font = ImageFont.truetype(FONT_LIGHT_PATH, 26)
    draw.text((w // 2, h - 26), "@agentejuridico", font=font,
              fill=(*GOLD, 170), anchor="mb")


def background_with_noise(W, H):
    """Fundo azul royal com gradiente + grain cinematográfico.
    O grain sutil (~6px de variação) elimina o visual 'digital liso'
    e dá profundidade às imagens dado/alerta/meme."""
    img = Image.new("RGB", (W, H), ROYAL_BLUE)
    draw = ImageDraw.Draw(img)
    # Gradiente de cima para baixo
    for y in range(H):
        t = y / H
        r = int(ROYAL_BLUE[0] * (1 - t * 0.25))
        g = int(ROYAL_BLUE[1] * (1 - t * 0.15))
        b = int(ROYAL_BLUE[2] * (1 - t * 0.08))
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    # Grain cinematográfico sutil — seed fixo = resultado determinístico
    rng = random.Random(7)
    pixels = img.load()
    for _ in range(W * H // 6):   # ~16% dos pixels afetados
        px = rng.randint(0, W - 1)
        py = rng.randint(0, H - 1)
        d = rng.randint(-7, 7)
        base = pixels[px, py]
        pixels[px, py] = (
            max(0, min(255, base[0] + d)),
            max(0, min(255, base[1] + d)),
            max(0, min(255, base[2] + d)),
        )
    return img


# ── /compose — fluxo existente (imagem AI + overlay de texto) ─────────────────

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

    composed_url = host_image(img_to_bytes(img))
    return {"composed_url": composed_url, "lines_rendered": lines}


# ── /compose/dado — post de estatística impactante ────────────────────────────

class DadoRequest(BaseModel):
    numero: str                    # "78%"  ou "200 mil"
    unidade: str = ""              # "das marcas no Brasil"
    descricao: str = ""            # "são registradas sem pesquisa prévia de anterioridade"
    cta: str = ""


@app.post("/compose/dado")
def compose_dado(req: DadoRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img  = background_with_noise(W, H)
    draw = ImageDraw.Draw(img)

    gold_bar(draw, W)

    # ── Label "DADO DO DIA" ──────────────────────────────────────────────────
    f_label = ImageFont.truetype(FONT_BOLD_PATH, 28)
    draw.text((W // 2, 36), "DADO DO DIA", font=f_label, fill=GOLD, anchor="mt")
    gold_accent_line(draw, 80, W, margin=120)

    # ── Número principal — escolhe tamanho que cabe ───────────────────────────
    numero_txt = req.numero.upper()
    for font_size in [210, 170, 140, 115, 95]:
        f_num = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        test_bbox = draw.textbbox((0, 0), numero_txt, font=f_num, anchor="lt")
        if test_bbox[2] - test_bbox[0] < W * 0.84:
            break

    # Centraliza usando anchor="lt" para evitar erros de bearing
    num_bbox_0 = draw.textbbox((0, 0), numero_txt, font=f_num, anchor="lt")
    num_w = num_bbox_0[2] - num_bbox_0[0]
    num_x = (W - num_w) // 2
    num_y = 105

    # Glow dourado
    for off in [4, 2]:
        draw.text((num_x + off, num_y + off), numero_txt, font=f_num,
                  fill=(*GOLD, 55), anchor="lt")
    draw.text((num_x, num_y), numero_txt, font=f_num, fill=WHITE, anchor="lt")

    # PONTO CRÍTICO: usa bbox ABSOLUTO do texto já renderizado para obter
    # o fundo real, eliminando erros de offset entre versões do Pillow
    abs_num_bbox = draw.textbbox((num_x, num_y), numero_txt, font=f_num, anchor="lt")
    y = abs_num_bbox[3] + 18   # fundo absoluto + padding

    # ── Unidade (ex: "dos desenvolvedores") ──────────────────────────────────
    if req.unidade:
        f_uni = ImageFont.truetype(FONT_REGULAR_PATH, 38)
        y = centered_wrap(draw, req.unidade.upper(), y, f_uni, GOLD, W, max_chars=32)
        y += 4

    gold_accent_line(draw, y + 14, W)
    y += 46

    # ── Descrição ─────────────────────────────────────────────────────────────
    if req.descricao:
        f_desc = ImageFont.truetype(FONT_REGULAR_PATH, 36)
        y = centered_wrap(draw, req.descricao, y, f_desc, WHITE, W, max_chars=38)

    # ── CTA — posicionado logo após o conteúdo, sem gap ──────────────────────
    if req.cta and y + 56 < H - 80:   # só desenha se couber
        y_cta = y + 56
        gold_accent_line(draw, y_cta - 20, W)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 34)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=40)

    watermark(draw, W, H)
    return {"composed_url": host_image(img_to_bytes(img, "PNG"), "PNG")}


# ── /compose/alerta — mito vs verdade ─────────────────────────────────────────

class AlertaRequest(BaseModel):
    mito: str                      # "CNPJ já protege sua marca"
    verdade: str                   # "São documentos completamente diferentes"
    cta: str = ""


@app.post("/compose/alerta")
def compose_alerta(req: AlertaRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img  = background_with_noise(W, H)
    draw = ImageDraw.Draw(img)

    # Barra vermelha topo
    draw.rectangle([(0, 0), (W, 7)], fill=RED)

    # "MITO" grande com destaque
    f_mito_title = ImageFont.truetype(FONT_BOLD_PATH, 100)
    draw.text((W // 2, 32), "MITO", font=f_mito_title, fill=RED, anchor="mt")

    # Ícone de alerta (triângulo) centralizado
    cx = W // 2
    tri_y = 175
    tri_s = 68
    pts = [(cx, tri_y), (cx - tri_s, tri_y + int(tri_s * 1.7)),
           (cx + tri_s, tri_y + int(tri_s * 1.7))]
    draw.polygon(pts, fill=(80, 10, 10), outline=RED)
    draw.polygon(pts, outline=RED, width=3)
    f_exc = ImageFont.truetype(FONT_BOLD_PATH, 60)
    draw.text((cx, tri_y + 20), "!", font=f_exc, fill=WHITE, anchor="mt")

    y = tri_y + int(tri_s * 1.7) + 28

    # Caixa do mito (fundo escuro-vermelho com borda)
    box_pad = 28
    f_mt = ImageFont.truetype(FONT_REGULAR_PATH, 42)
    lines_m = textwrap.wrap(req.mito, width=28)[:2]  # máx 2 linhas — evita overflow
    box_h = len(lines_m) * 56 + box_pad * 2
    draw.rounded_rectangle([(50, y), (W - 50, y + box_h)],
                            radius=14, fill=(40, 5, 5), outline=(140, 30, 30), width=2)
    y_m = y + box_pad
    for line in lines_m:
        bbox_m = draw.textbbox((0, 0), line, font=f_mt, anchor="lt")
        lw = bbox_m[2] - bbox_m[0]
        lx = (W - lw) // 2
        # Texto riscado (tachado)
        draw.text((lx, y_m), line, font=f_mt, fill=(210, 80, 80))
        mid = y_m + 21 + 2   # 42 // 2 — font.size removido no Pillow 11
        draw.line([(lx, mid), (lx + lw, mid)], fill=(210, 80, 80), width=2)
        y_m += 56
    y += box_h + 32

    # Separador dourado
    gold_accent_line(draw, y, W)
    y += 28

    # "VERDADE" label
    f_vl = ImageFont.truetype(FONT_BOLD_PATH, 46)
    y = centered(draw, "VERDADE:", y, f_vl, GOLD, W)
    y += 6

    # Texto da verdade
    f_vd = ImageFont.truetype(FONT_REGULAR_PATH, 42)
    y = centered_wrap(draw, req.verdade, y, f_vd, WHITE, W, max_chars=30)

    # CTA
    if req.cta and y + 50 < H - 80:   # só desenha se couber
        y_cta = y + 50
        gold_accent_line(draw, y_cta - 18, W)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 34)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=42)

    watermark(draw, W, H)
    return {"composed_url": host_image(img_to_bytes(img, "PNG"), "PNG")}


# ── /compose/meme — ironia jurídica ───────────────────────────────────────────

class MemeRequest(BaseModel):
    setup: str                     # "Quando o cliente acha que CNPJ protege a marca"
    reacao: str = "SÉRIO MESMO?"   # Texto grande no centro
    punchline: str = ""            # "CNPJ não protege nada. Só o registro de marca."
    cta: str = ""


@app.post("/compose/meme")
def compose_meme(req: MemeRequest):
    ensure_fonts()
    W, H = 1080, 1080
    img  = background_with_noise(W, H)
    draw = ImageDraw.Draw(img)

    gold_bar(draw, W)

    # Sub-label discreto
    f_sub = ImageFont.truetype(FONT_LIGHT_PATH, 28)
    draw.text((W // 2, 36), "@agentejuridico explica:", font=f_sub, fill=MUTED, anchor="mt")

    # Setup (contexto inicial)
    f_setup = ImageFont.truetype(FONT_REGULAR_PATH, 52)
    y = 108
    y = centered_wrap(draw, req.setup, y, f_setup, WHITE, W, max_chars=24)

    gold_accent_line(draw, y + 18, W)
    y += 50

    # Reação central — dourado, grande, impacto
    reacao_txt = req.reacao.upper()
    for font_size in [110, 90, 72, 58]:
        f_reac = ImageFont.truetype(FONT_BOLD_PATH, font_size)
        lines_r = textwrap.wrap(reacao_txt, width=16)
        total_w = max(
            draw.textbbox((0, 0), line, font=f_reac, anchor="lt")[2]
            for line in lines_r
        )
        if total_w < W * 0.90:
            break
    for line in lines_r:
        bbox_r = draw.textbbox((0, 0), line, font=f_reac, anchor="lt")
        rw = bbox_r[2] - bbox_r[0]
        # Sombra glow
        draw.text(((W - rw) // 2 + 3, y + 3), line, font=f_reac, fill=(*GOLD, 60))
        draw.text(((W - rw) // 2, y), line, font=f_reac, fill=GOLD)
        y += int(font_size * 1.12)   # font.size removido no Pillow 11

    gold_accent_line(draw, y + 18, W)
    y += 44

    # Punchline
    if req.punchline:
        f_punch = ImageFont.truetype(FONT_REGULAR_PATH, 46)
        y = centered_wrap(draw, req.punchline, y, f_punch, WHITE, W, max_chars=28)

    # CTA
    if req.cta and y + 50 < H - 80:   # só desenha se couber
        y_cta = y + 50
        gold_accent_line(draw, y_cta - 18, W)
        f_cta = ImageFont.truetype(FONT_BOLD_PATH, 36)
        centered_wrap(draw, req.cta, y_cta, f_cta, GOLD, W, max_chars=40)

    watermark(draw, W, H)
    return {"composed_url": host_image(img_to_bytes(img, "PNG"), "PNG")}


# ── /compose/auto — roteamento automático por FORMATO ────────────────────────

def extract_field(text: str, field: str) -> str:
    """Extrai FIELD: valor do output pipe-separado do Estrategista."""
    for part in text.split("|"):
        part = part.strip()
        if part.upper().startswith(field.upper() + ":"):
            return part[len(field) + 1:].strip()
    return ""


class AutoRequest(BaseModel):
    image_url: str = ""
    estrategista_output: str
    brand_handle: str = "@agentejuridico"


@app.post("/compose/auto")
def compose_auto(req: AutoRequest):
    """
    Detecta FORMATO no estrategista_output e roteia:
      padrao → /compose   (usa image_url + overlay de texto sobre imagem AI)
      dado   → /compose/dado   (estatística em destaque sobre fundo royal blue)
      alerta → /compose/alerta (mito vs verdade)
      meme   → /compose/meme   (ironia profissional)
    """
    formato = extract_field(req.estrategista_output, "FORMATO").lower().strip()
    cta = extract_field(req.estrategista_output, "CTA")

    if formato == "dado":
        numero   = extract_field(req.estrategista_output, "EXTRA1") or extract_field(req.estrategista_output, "NUMERO")
        unidade  = extract_field(req.estrategista_output, "EXTRA2") or extract_field(req.estrategista_output, "UNIDADE")
        descricao = extract_field(req.estrategista_output, "EXTRA3") or extract_field(req.estrategista_output, "DESCRICAO")
        return compose_dado(DadoRequest(numero=numero, unidade=unidade, descricao=descricao, cta=cta))

    elif formato == "alerta":
        mito    = extract_field(req.estrategista_output, "EXTRA1") or extract_field(req.estrategista_output, "MITO")
        verdade = extract_field(req.estrategista_output, "EXTRA2") or extract_field(req.estrategista_output, "VERDADE")
        return compose_alerta(AlertaRequest(mito=mito, verdade=verdade, cta=cta))

    elif formato == "meme":
        setup     = extract_field(req.estrategista_output, "EXTRA1") or extract_field(req.estrategista_output, "SETUP")
        reacao    = extract_field(req.estrategista_output, "EXTRA2") or "SÉRIO MESMO?"
        punchline = extract_field(req.estrategista_output, "EXTRA3") or extract_field(req.estrategista_output, "PUNCHLINE")
        return compose_meme(MemeRequest(setup=setup, reacao=reacao, punchline=punchline, cta=cta))

    else:  # padrao (default)
        if not req.image_url:
            raise HTTPException(status_code=400, detail="image_url obrigatório para formato padrao")
        return compose(ComposeRequest(
            image_url=req.image_url,
            estrategista_output=req.estrategista_output,
            brand_handle=req.brand_handle,
        ))


# ── Servir imagens hospedadas localmente ─────────────────────────────────────

@app.get("/image/{filename}")
def serve_image(filename: str):
    filepath = IMAGE_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    media_type = "image/png" if filename.endswith(".png") else "image/jpeg"
    return FileResponse(filepath, media_type=media_type)


# ── Health check ─────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.4"}
