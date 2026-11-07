"""poizon.py — источник товаров с Poizon (thepoizon.ru) без JS-браузера.

Как это работает
---------------
Страницы thepoizon.ru отдаются готовым HTML (SSR) с встроенным JSON
`<script id="__NEXT_DATA__">`. В нём уже лежат:
  * название товара;
  * цена в рублях (minSpuPrice на листинге, minPrice по размерам на странице товара);
  * фото с официального CDN (cdn-img.thepoizon.ru) — обычно уже на белом фоне.
Поэтому обычным HTTP-запросом (без Selenium/Playwright и без капчи) получаем
и фото, и цену — ровно то, что раньше не получалось.

Вежливость: запросы редкие (1 страница = 1 запрос, паузы 2.5-5 с), результаты
кэшируются в sqlite, на ошибки 403/429 бот реагирует паузой, а не перебором.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import quote, urljoin

import requests

BASE_DEFAULT = "https://www.thepoizon.ru"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Referer": "https://www.thepoizon.ru/",
    "Connection": "keep-alive",
}

_IMG_HOSTS = ("thepoizon.ru", "poizon.com", "hupucdn.com", "dewucdn.com")
# служебные картинки самого сайта (иконки, баннеры, логотипы брендов) — не товары
_IMG_JUNK = ("node-common", "brand-logo", "/icon", "avatar", "banner", "sprite",
             "/ranking/", "/trends/", "usericon", "video")


class PoizonError(RuntimeError):
    """Страница не отдала данные (блок, капча, изменилась разметка)."""


@dataclass
class Product:
    spu_id: int
    title: str
    path: str
    price: float | None = None
    price_text: str = ""
    currency: str = "RUB"
    main_image: str = ""
    gallery: list[str] = field(default_factory=list)
    brand: str = ""
    article: str = ""
    category: str = ""
    sold_text: str = ""
    source: str = ""
    model: str = ""
    color: str = ""
    sizes: list[dict] = field(default_factory=list)

    @property
    def url(self) -> str:
        return urljoin(BASE_DEFAULT, self.path)

    def all_images(self) -> list[str]:
        out, seen = [], set()
        for u in [self.main_image] + self.gallery:
            if u and u not in seen and is_product_image(u):
                seen.add(u)
                out.append(u)
        return out


def is_product_image(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    low = url.lower().split("?")[0]
    if not low.endswith((".jpg", ".jpeg", ".png", ".webp")):
        return False
    if not any(h in low for h in _IMG_HOSTS):
        return False
    if any(j in low for j in _IMG_JUNK):
        return False
    return True


def _money_to_float(node) -> float | None:
    """minSpuPrice / minPrice -> float в рублях."""
    if not isinstance(node, dict):
        return None
    money = node.get("money") or {}
    for key in ("amount", "minUnitVal"):
        raw = money.get(key)
        if raw in (None, ""):
            continue
        try:
            val = float(str(raw).replace(" ", "").replace(",", "."))
        except ValueError:
            continue
        if key == "minUnitVal":
            val = val / 100.0
        if val > 0:
            return round(val, 2)
    txt = node.get("localizedDisplayText") or node.get("absText") or ""
    digits = re.sub(r"[^\d]", "", txt)
    if digits:
        return float(digits)
    return None


def _money_text(node) -> str:
    if isinstance(node, dict):
        txt = node.get("localizedDisplayText") or node.get("absText") or ""
        if txt:
            return txt.replace("\xa0", " ").strip()
    return ""


def _looks_blocked(html: str) -> bool:
    head = (html or "")[:3000].lower()
    return "security verification" in head or "captcha" in head


def _extract_next_data(html: str) -> dict:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise PoizonError("__NEXT_DATA__ не найден — страница отдаёт пустую оболочку")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise PoizonError(f"__NEXT_DATA__ не читается: {exc}") from exc


def _collect_urls(obj, out: list[str], depth: int = 0) -> None:
    if depth > 9 or obj is None:
        return
    if isinstance(obj, dict):
        for key, val in obj.items():
            if isinstance(val, str) and is_product_image(val):
                out.append(val)
            elif isinstance(val, dict) and key in ("imageModels", "imageModelList",
                                                   "saleImages", "saleImageModels",
                                                   "detailImageList", "sizeImageList"):
                _collect_urls(val, out, depth + 1)
            else:
                _collect_urls(val, out, depth + 1)
    elif isinstance(obj, list):
        for val in obj[:80]:
            _collect_urls(val, out, depth + 1)


class PoizonClient:
    def __init__(self, base_url: str = BASE_DEFAULT,
                 delay: tuple[float, float] = (2.5, 5.0),
                 timeout: int = 30, verbose: bool = True,
                 block_cooldown_minutes: int = 45):
        self.base = base_url.rstrip("/")
        self.delay = delay
        self.timeout = timeout
        self.verbose = verbose
        self.block_cooldown_minutes = max(5, block_cooldown_minutes)
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        self._last_request = 0.0
        self.blocked_until = 0.0
        self.on_block = None  # callback(unix_ts): куда сохранить окончание кулдауна

    # ------------------------------------------------------------------ low
    def _polite_pause(self) -> None:
        wait = self._last_request + random.uniform(*self.delay) - time.time()
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.time()

    def _remember_block(self, until: float) -> None:
        self.blocked_until = until
        if self.on_block:
            try:
                self.on_block(until)
            except Exception:
                pass

    def _get(self, path: str, retries: int = 2) -> str:
        """Один вежливый заход: при 403/429/'Security Verification' НЕ сидим и
        не долбим сайт, а быстро выходим и запоминаем кулдаун (он в sqlite)."""
        url = self.base + path
        if time.time() < self.blocked_until:
            left = int(self.blocked_until - time.time())
            raise PoizonError(f"{path}: сайт ограничивает запросы, продолжение "
                              f"через {left} c (кулдаун)")
        last_err = None
        for attempt in range(1, retries + 1):
            self._polite_pause()
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_err = f"сеть: {exc}"
                time.sleep(5 * attempt)
                continue
            if resp.status_code == 200:
                if _looks_blocked(resp.text):
                    self._remember_block(time.time() + self.block_cooldown_minutes * 60)
                    raise PoizonError(f"{path}: сайт показал 'Security Verification'")
                if self.blocked_until:
                    self._remember_block(0.0)
                return resp.text
            if resp.status_code in (403, 429, 503):
                self._remember_block(time.time() + self.block_cooldown_minutes * 60)
                raise PoizonError(f"{path}: HTTP {resp.status_code} — сайт дросселирует, "
                                  f"кулдаун {self.block_cooldown_minutes} мин")
            last_err = f"HTTP {resp.status_code}"
            if resp.status_code == 404:
                break
            time.sleep(3 * attempt)
        raise PoizonError(f"{path}: {last_err}")

    # ------------------------------------------------------------- listing
    def _listing_path(self, kind: str, value: str, page: int) -> str:
        kind = (kind or "search").lower()
        value = value.strip()
        if kind == "brand":
            path = f"/brand/{value.lstrip('/')}"
        elif kind == "category":
            path = f"/category/{value.lstrip('/')}"
        else:
            path = f"/search?keyword={quote(value)}"
        if kind != "search":
            path += f"?page={page}" if "?" not in path else f"&page={page}"
        return path

    def listing(self, kind: str, value: str, pages: int = 1) -> list[Product]:
        """Достаёт товары из выдачи: search / brand / category."""
        products: list[Product] = []
        source = f"{kind}:{value}"
        for page in range(1, max(1, pages) + 1):
            if kind == "search" and page > 1:
                break  # SSR-поиск отдаёт только первую страницу
            try:
                html = self._get(self._listing_path(kind, value, page))
                page_props = _extract_next_data(html).get("props", {}).get("pageProps", {})
            except PoizonError as exc:
                if self.verbose:
                    print(f"  ! {source} стр.{page}: {exc}")
                continue
            for raw in page_props.get("spuList") or []:
                prod = self._product_from_spu(raw, source)
                if prod:
                    products.append(prod)
            if self.verbose:
                print(f"  {source} стр.{page}: {len(page_props.get('spuList') or [])} "
                      f"товаров, всего на сайте {page_props.get('total')}")
        return products

    def _product_from_spu(self, raw: dict, source: str) -> Product | None:
        spu_id = raw.get("spuId") or raw.get("productId")
        path = raw.get("url") or ""
        title = (raw.get("title") or "").strip()
        if not spu_id or not path or not title:
            return None
        price_node = raw.get("minSpuPrice")
        return Product(
            spu_id=int(spu_id),
            title=title,
            path=path,
            price=_money_to_float(price_node),
            price_text=_money_text(price_node),
            currency=(raw.get("currency") or "RUB"),
            main_image=raw.get("logoUrl") or "",
            brand=raw.get("brandName") or "",
            article=raw.get("articleNumber") or "",
            category=raw.get("categoryName") or raw.get("level2CategoryName") or "",
            sold_text=(raw.get("saleTag") or "").replace("\xa0", " "),
            source=source,
        )

    # -------------------------------------------------------------- detail
    def detail(self, product: Product) -> Product:
        """Страница товара: точная минимальная цена по размерам + галерея фото."""
        html = self._get(product.path)
        page_props = _extract_next_data(html).get("props", {}).get("pageProps", {})
        goods = page_props.get("goodsDetail") or {}
        price_info = page_props.get("priceInfo") or {}

        prices: list[float] = []
        sizes: list[dict] = []
        for sku in (price_info.get("skus") or [])[:60]:
            price = _money_to_float(sku.get("minPrice")) or _money_to_float(sku.get("price"))
            if price:
                prices.append(price)
                title = (sku.get("skuTitle") or "").strip()
                size = title.replace(product.title, "").strip() if product.title else title
                sizes.append({"sku_id": sku.get("skuId"), "size": size, "price": price})

        for node in (goods.get("price"), goods.get("skuMinPriceInfoDTO")):
            price = _money_to_float(node)
            if price:
                prices.append(price)

        if prices:
            product.price = min(prices)
            product.price_text = _money_text((price_info.get("skus") or [{}])[0].get("minPrice")) \
                or product.price_text
        product.sizes = sizes

        urls: list[str] = []
        _collect_urls(goods.get("imageModels"), urls)
        _collect_urls(goods.get("imageModelList"), urls)
        _collect_urls(goods.get("saleImageModels"), urls)
        _collect_urls(goods.get("saleImages"), urls)
        _collect_urls(goods.get("imageAndText"), urls)
        clean: list[str] = []
        for u in urls:
            u = u.split("?")[0]
            if u not in clean:
                clean.append(u)
        if clean:
            product.gallery = clean

        # характеристики: модель, цвет, артикул -> короткое и понятное название поста
        props: dict[str, str] = {}
        for item in goods.get("baseProperties") or []:
            key = (item.get("key") or "").strip()
            val = (item.get("value") or "").strip()
            if key and val:
                props.setdefault(key, val)
        for block in (goods.get("propertyModule") or {}).get("propertyBlocks") or []:
            for prop in block.get("propertyList") or []:
                key = (prop.get("name") or "").strip()
                val = (prop.get("value") or "").strip()
                if key and val:
                    props.setdefault(key, val)
        product.model = props.get("Модель") or product.model
        product.color = props.get("Основной цвет") or product.color
        product.article = props.get("Основной артикул") or product.article
        if not product.title:
            product.title = (goods.get("productTextInfo") or {}).get("title", "") or product.title
        return product

    def by_url(self, url: str) -> Product:
        """Товар по ссылке или spuId — для ручного добавления."""
        match = re.search(r"/product/[^/?#]+", url)
        digits = re.search(r"(\d{7,})", url)
        path = match.group(0) if match else url
        prod = Product(spu_id=int(digits.group(1)) if digits else 0, title="", path=path)
        return self.detail(prod)
