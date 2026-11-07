"""imageprep.py — фото Poizon -> аккуратная картинка на белом фоне для Telegram.

Никакой нейросетевой генерации: берётся РЕАЛЬНОЕ фото товара с CDN Poizon
(обычно оно уже на белом фоне) и приводится к единому эстетичному формату:
  * проверка, что фон действительно белый (по углам изображения);
  * обрезка лишнего, центрирование;
  * белый холст 1080x1350 (4:5) с одинаковыми полями — все посты выглядят одинаково;
  * при photos_per_post > 1 — коллаж 1-3 ракурса на том же белом холсте.

Опционально (если установлен rembg) вырезает фон перед укладкой на белый.
"""
from __future__ import annotations

import hashlib
import io
import os
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


class ImageError(RuntimeError):
    pass


@dataclass
class Prepared:
    path: str
    width: int
    height: int
    white_background: bool
    used_urls: list[str]


def download_image(url: str, timeout: int = 30, max_side: int = 1600) -> Image.Image:
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": UA, "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise ImageError(f"не скачалось {url[:80]}: {exc}") from exc
    if resp.status_code != 200:
        raise ImageError(f"HTTP {resp.status_code} для {url[:80]}")
    try:
        img = Image.open(io.BytesIO(resp.content))
        img.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageError(f"не картинка: {url[:80]} ({exc})") from exc
    img = ImageOps.exif_transpose(img)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if max(img.size) > max_side:
        img = ImageOps.contain(img, (max_side, max_side), method=Image.Resampling.LANCZOS)
    return img.convert("RGB")


def background_is_white(img: Image.Image, threshold: int = 232, tolerance: int = 14) -> bool:
    """Считаем фон белым, если углы и середины кроёв светлые и почти бесцветные."""
    w, h = img.size
    if w < 80 or h < 80:
        return False
    pts = []
    for frac_x, frac_y in ((0.04, 0.04), (0.96, 0.04), (0.04, 0.96), (0.96, 0.96),
                           (0.5, 0.03), (0.5, 0.97), (0.03, 0.5), (0.97, 0.5)):
        x = min(w - 1, int(w * frac_x))
        y = min(h - 1, int(h * frac_y))
        pts.append(img.getpixel((x, y)))
    for r, g, b in pts:
        if min(r, g, b) < threshold:
            return False
        if max(r, g, b) - min(r, g, b) > tolerance:
            return False
    return True


def _trim(img: Image.Image, white_threshold: int = 246) -> Image.Image:
    """Обрезает равномерные белые поля вокруг товара."""
    try:
        gray = ImageOps.autocontrast(img.convert("L"), cutoff=1)
        mask = gray.point(lambda p: 0 if p >= white_threshold else 255)
        bbox = mask.getbbox()
        if bbox and (bbox[2] - bbox[0]) > img.width * 0.25 and (bbox[3] - bbox[1]) > img.height * 0.25:
            return img.crop(bbox)
    except Exception:
        pass
    return img


def _remove_background(img: Image.Image) -> Image.Image:
    """Если установлен rembg — вырезаем товар и кладём на чистый белый."""
    try:
        from rembg import remove  # type: ignore
    except ImportError:
        return img
    try:
        cut = remove(img)
        if cut.mode != "RGBA":
            cut = cut.convert("RGBA")
        base = Image.new("RGB", cut.size, (255, 255, 255))
        base.paste(cut, (0, 0), cut)
        return base
    except Exception:
        return img


def compose(images: list[Image.Image], canvas: tuple[int, int],
            padding_percent: int = 12, quality: int = 90,
            out_path: str = "out/post.jpg", salt: str = "") -> Prepared:
    """Кладёт 1-3 фото на единый белый холст. Коллаж не смешивает товары."""
    cw, ch = canvas
    pad = int(min(cw, ch) * padding_percent / 100)
    inner_w, inner_h = cw - 2 * pad, ch - 2 * pad

    imgs = [ImageOps.contain(i, (inner_w, inner_h), method=Image.Resampling.LANCZOS)
            for i in images[:3]]
    if not imgs:
        raise ImageError("нет ни одного подходящего изображения")

    sheet = Image.new("RGB", (cw, ch), (255, 255, 255))

    if len(imgs) == 1:
        img = imgs[0]
        sheet.paste(img, ((cw - img.width) // 2, (ch - img.height) // 2))
    else:
        cell_h = (inner_h - pad * (len(imgs) - 1)) // len(imgs)
        imgs = [ImageOps.contain(i, (inner_w, cell_h), method=Image.Resampling.LANCZOS)
                for i in imgs]
        y = pad
        for img in imgs:
            sheet.paste(img, ((cw - img.width) // 2, y + (cell_h - img.height) // 2))
            y += cell_h + pad

    if salt:
        # невидимая метка: каждый пост уникален по bytes-hash,
        # Telegram не склеивает дубли и не отдаёт "file_id is not modified"
        digest = hashlib.sha256(salt.encode("utf-8")).digest()
        for i in range(3):
            sheet.putpixel((1 + i, ch - 1), (digest[i], digest[i + 3], digest[i + 6]))

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    sheet.save(out_path, format="JPEG", quality=quality, optimize=True)
    return Prepared(path=out_path, width=cw, height=ch,
                    white_background=True, used_urls=[])


def prepare_post_image(urls: list[str], out_path: str,
                       canvas: tuple[int, int] = (1080, 1350),
                       padding_percent: int = 12, quality: int = 90,
                       photos_per_post: int = 1, require_white: bool = True,
                       remove_bg: bool = False, salt: str = "") -> Prepared:
    """Основная функция: список URL -> готовый JPEG для Telegram."""
    if not urls:
        raise ImageError("у товара нет фото")
    chosen: list[Image.Image] = []
    used: list[str] = []
    white_ok = False
    errors: list[str] = []
    for url in urls[: photos_per_post * 3]:
        try:
            img = download_image(url)
        except ImageError as exc:
            errors.append(str(exc))
            continue
        white = background_is_white(img)

        if remove_bg:
            img = _remove_background(img)
            white = background_is_white(img)
        img = _trim(img)
        chosen.append(img)
        used.append(url)
        white_ok = white_ok or white
        if len(chosen) >= max(1, photos_per_post):
            break

    if not chosen:
        raise ImageError("не удалось получить фото: " + "; ".join(errors[:3]))
    if require_white and not white_ok:
        raise ImageError("все фото товара не на белом фоне")

    prepared = compose(chosen, canvas, padding_percent, quality, out_path, salt)
    prepared.used_urls = used
    prepared.white_background = white_ok
    return prepared
