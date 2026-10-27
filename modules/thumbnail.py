"""Professional thumbnail composer (Pillow only — no extra deps).

Takes a dedicated, object-rich thumbnail image (generated from the model's
thumbnail_prompt) and treats it like a senior designer would: cinematic grade,
depth/vignette, accent spotlight glow, a bold stroked + shadowed headline, an
accent keyword tag, and channel branding. Produces two outputs:

    thumb_yt.jpg  1280x720  (YouTube — focal image left, text right, blur-fill)
    thumb_v.jpg   1080x1920 (IG/vertical cover — focal upper, text lower third)
"""

import logging
import re
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

logger = logging.getLogger("pipeline.thumbnail")

FONT_PATH = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "Anton-Regular.ttf"

_DEFAULT_ACCENT = (255, 211, 79)  # warm gold


# ── helpers ──────────────────────────────────────────────────────────────────

def accent_rgb_from_ass(ass_color: str) -> tuple:
    """ASS '&H00BBGGRR' (BGR) → (R, G, B)."""
    hexpart = re.sub(r"[^0-9A-Fa-f]", "", ass_color or "")
    if len(hexpart) >= 6:
        hexpart = hexpart[-6:]
        bb, gg, rr = hexpart[0:2], hexpart[2:4], hexpart[4:6]
        try:
            return (int(rr, 16), int(gg, 16), int(bb, 16))
        except ValueError:
            pass
    return _DEFAULT_ACCENT


def _font(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), max(8, int(size)))
    except Exception:
        return ImageFont.load_default()


def _line_size(font, text, stroke=0):
    img = Image.new("L", (4, 4))
    d = ImageDraw.Draw(img)
    l, t, r, b = d.textbbox((0, 0), text, font=font, stroke_width=stroke)
    return r - l, b - t


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Scale to fully cover (w,h) then center-crop."""
    iw, ih = img.size
    scale = max(w / iw, h / ih)
    nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - w) // 2
    y = (nh - h) // 2
    return img.crop((x, y, x + w, y + h))


def _contain(img: Image.Image, w: int, h: int) -> Image.Image:
    iw, ih = img.size
    scale = min(w / iw, h / ih)
    return img.resize((max(1, int(iw * scale)), max(1, int(ih * scale))), Image.LANCZOS)


def _grade(img: Image.Image) -> Image.Image:
    """Cinematic pop: contrast + saturation + sharpness + slight brightness."""
    img = ImageEnhance.Contrast(img).enhance(1.18)
    img = ImageEnhance.Color(img).enhance(1.35)
    img = ImageEnhance.Sharpness(img).enhance(1.6)
    img = ImageEnhance.Brightness(img).enhance(1.03)
    return img


def _vignette(img: Image.Image, strength: float = 0.55) -> Image.Image:
    """Darken edges so the eye goes to the focal area."""
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    inset_x, inset_y = int(w * 0.10), int(h * 0.10)
    d.ellipse([-inset_x, -inset_y, w + inset_x, h + inset_y], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(min(w, h) * 0.12))
    dark = ImageEnhance.Brightness(img).enhance(1.0 - strength)
    return Image.composite(img, dark, mask)


def _linear_gradient(w: int, h: int, side: str, peak: int = 200) -> Image.Image:
    """L-mode gradient: 0 → peak across one edge (for a dark text scrim alpha)."""
    if side in ("bottom", "top"):
        base = Image.new("L", (1, h))
        for y in range(h):
            f = y / max(h - 1, 1)
            v = f if side == "bottom" else (1 - f)
            base.putpixel((0, y), int(v * peak))
    else:  # left / right
        base = Image.new("L", (w, 1))
        for x in range(w):
            f = x / max(w - 1, 1)
            v = f if side == "right" else (1 - f)
            base.putpixel((x, 0), int(v * peak))
    return base.resize((w, h))


def _accent_glow(size, center, accent, radius_frac=0.42, intensity=0.55):
    """Screen-blendable RGB glow: black field with a blurred accent ellipse."""
    w, h = size
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    r = int(min(w, h) * radius_frac)
    cx, cy = center
    col = tuple(int(c * intensity) for c in accent)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    return glow.filter(ImageFilter.GaussianBlur(r * 0.55))


def _fit_lines(text: str, max_w: int, max_h: int, max_lines: int = 3,
               hi: int = 200, lo: int = 30):
    """Largest Anton size whose word-wrapped lines fit (max_w, max_h, max_lines)."""
    words = text.upper().split()
    for size in range(hi, lo - 1, -4):
        font = _font(size)
        stroke = max(2, size // 9)
        # greedy wrap
        lines, cur = [], ""
        ok = True
        for word in words:
            trial = (cur + " " + word).strip()
            tw, _ = _line_size(font, trial, stroke)
            if tw <= max_w or not cur:
                cur = trial
            else:
                lines.append(cur)
                cur = word
            if _line_size(font, word, stroke)[0] > max_w:
                ok = False
                break
        if cur:
            lines.append(cur)
        if not ok or len(lines) > max_lines:
            continue
        line_h = _line_size(font, "AyжJ", stroke)[1]
        total_h = int(line_h * len(lines) * 1.08)
        if total_h <= max_h:
            return font, lines, stroke, line_h
    # fallback smallest
    font = _font(lo)
    stroke = max(2, lo // 9)
    return font, [text.upper()], stroke, _line_size(font, "Ay", stroke)[1]


def _draw_headline(base: Image.Image, lines, font, stroke, line_h,
                   box_left: int, box_right: int, cy: int):
    """Stroked + drop-shadow headline, centered in the [box_left,box_right] column."""
    w, h = base.size
    cx = (box_left + box_right) // 2
    block_h = int(line_h * len(lines) * 1.08)
    y = cy - block_h // 2

    # drop shadow layer (blurred)
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    yy = y
    for ln in lines:
        tw, _ = _line_size(font, ln, stroke)
        x = cx - tw // 2
        sd.text((x + 6, yy + 8), ln, font=font, fill=(0, 0, 0, 210),
                stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
        yy += int(line_h * 1.08)
    shadow = shadow.filter(ImageFilter.GaussianBlur(7))
    base.alpha_composite(shadow)

    # main text
    d = ImageDraw.Draw(base)
    yy = y
    for ln in lines:
        tw, _ = _line_size(font, ln, stroke)
        x = cx - tw // 2
        d.text((x, yy), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        yy += int(line_h * 1.08)
    return y


def _draw_keyword_tag(base: Image.Image, keyword: str, accent, cx: int, top_y: int, scale: int):
    """Accent rounded box with the keyword (the 'highlighted' attention word)."""
    if not keyword:
        return top_y
    kw = keyword.upper().strip()
    font = _font(scale)
    tw, th = _line_size(font, kw)
    pad_x, pad_y = int(scale * 0.45), int(scale * 0.22)
    bw, bh = tw + pad_x * 2, th + pad_y * 2
    x0 = cx - bw // 2
    y0 = top_y - bh
    d = ImageDraw.Draw(base)
    try:
        d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=int(bh * 0.22), fill=accent + (255,))
    except Exception:
        d.rectangle([x0, y0, x0 + bw, y0 + bh], fill=accent + (255,))
    # readable text colour on the accent (luminance check)
    lum = 0.299 * accent[0] + 0.587 * accent[1] + 0.114 * accent[2]
    fg = (20, 20, 20, 255) if lum > 150 else (255, 255, 255, 255)
    d.text((cx - tw // 2, y0 + pad_y), kw, font=font, fill=fg)
    return y0 - int(scale * 0.25)


def _draw_branding(base: Image.Image, channel_name: str, size_px: int):
    if not channel_name:
        return
    font = _font(size_px)
    txt = channel_name.upper()
    d = ImageDraw.Draw(base)
    tw, th = _line_size(font, txt, 2)
    x = base.size[0] - tw - int(size_px * 1.1)
    y = int(size_px * 0.6)
    d.text((x, y), txt, font=font, fill=(255, 255, 255, 170),
           stroke_width=2, stroke_fill=(0, 0, 0, 170))


def _finish(img: Image.Image) -> Image.Image:
    img = img.filter(ImageFilter.UnsharpMask(radius=2.2, percent=120, threshold=2))
    img = ImageEnhance.Color(img).enhance(1.06)
    return img


def _save_jpg(img: Image.Image, out_path: str, max_bytes: int = 2_000_000):
    img = img.convert("RGB")
    q = 92
    while q >= 60:
        img.save(out_path, "JPEG", quality=q, optimize=True)
        if Path(out_path).stat().st_size <= max_bytes:
            return
        q -= 6
    img.save(out_path, "JPEG", quality=60, optimize=True)


# ── main compose ─────────────────────────────────────────────────────────────

def compose(src_path: str, out_path: str, text: str, keyword: str,
            accent, channel_name: str, size: tuple):
    w, h = size
    landscape = w >= h
    src = Image.open(src_path).convert("RGB")

    if landscape:
        # blur-fill background + sharp portrait on the left third
        bg = _cover(src, w, h).filter(ImageFilter.GaussianBlur(38))
        bg = ImageEnhance.Brightness(bg).enhance(0.5)
        base = bg.convert("RGBA")
        fg = _contain(src, int(w * 0.46), int(h * 0.94))
        fg = _grade(fg)
        fx = int(w * 0.045)
        fy = (h - fg.size[1]) // 2
        focal = (fx + fg.size[0] // 2, h // 2)
        # accent spotlight behind the focal image
        base = ImageChops.screen(base.convert("RGB"),
                                 _accent_glow((w, h), focal, accent)).convert("RGBA")
        base.paste(fg, (fx, fy))
        base = _vignette(base.convert("RGB")).convert("RGBA")
        text_l, text_r = int(w * 0.50), int(w * 0.965)
        # right-side dark scrim for legibility
        scrim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        grad = _linear_gradient(w, h, "right", peak=150)
        scrim.putalpha(grad)
        base.alpha_composite(scrim)
        head_max_w = text_r - text_l
        font, lines, stroke, line_h = _fit_lines(text, head_max_w, int(h * 0.62),
                                                  max_lines=4, hi=120, lo=34)
        kw_scale = max(26, int(line_h * 0.5))
        brand_px = 26
        cy = int(h * 0.56)
    else:
        # portrait cover, text in the lower third
        base = _cover(src, w, h)
        base = _grade(base)
        focal = (int(w * 0.5), int(h * 0.34))
        base = ImageChops.screen(base, _accent_glow((w, h), focal, accent, radius_frac=0.36))
        base = _vignette(base).convert("RGBA")
        # bottom dark scrim
        scrim = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        grad = _linear_gradient(w, h, "bottom", peak=215)
        scrim.putalpha(grad)
        base.alpha_composite(scrim)
        text_l, text_r = int(w * 0.06), int(w * 0.94)
        head_max_w = text_r - text_l
        font, lines, stroke, line_h = _fit_lines(text, head_max_w, int(h * 0.30),
                                                  max_lines=3, hi=200, lo=60)
        kw_scale = max(40, int(line_h * 0.42))
        brand_px = 40
        cy = int(h * 0.72)

    # keyword tag above headline block, then headline, then branding
    block_h = int(line_h * len(lines) * 1.08)
    cx = (text_l + text_r) // 2
    _draw_keyword_tag(base, keyword, tuple(accent), cx, cy - block_h // 2 - int(line_h * 0.25), kw_scale)
    _draw_headline(base, lines, font, stroke, line_h, text_l, text_r, cy)
    _draw_branding(base, channel_name, brand_px)

    final = _finish(base.convert("RGB"))
    _save_jpg(final, out_path)
    logger.info(f"thumbnail composed → {Path(out_path).name} ({w}x{h})")


def generate_thumbnails(src_path: str, out_dir: str, text: str, keyword: str = "",
                        accent_color: str = "", channel_name: str = "") -> dict:
    """Produce the YouTube (16:9) + vertical (9:16) thumbnails. Returns paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    accent = accent_rgb_from_ass(accent_color)
    text = (text or "").strip() or "WATCH THIS"

    yt = str(out / "thumb_yt.jpg")
    vert = str(out / "thumb_v.jpg")
    result = {}
    try:
        compose(src_path, yt, text, keyword, accent, channel_name, (1280, 720))
        result["thumbnail_yt"] = yt
    except Exception as e:
        logger.warning(f"YT thumbnail failed: {e}")
    try:
        compose(src_path, vert, text, keyword, accent, channel_name, (1080, 1920))
        result["thumbnail_v"] = vert
    except Exception as e:
        logger.warning(f"Vertical thumbnail failed: {e}")
    return result
