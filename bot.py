"""bot.py — EasyBuyer Poizon: 4 поста в день в @easybuyerpz с реальными фото и ценами Poizon.

Чем эта версия отличается от прежней (easybuyer-cloud на BotHost):
  * пост больше не "заранее подготовленный текст": название, цена и фото берутся
    из живой карточки Poizon (thepoizon.ru, SSR-JSON) в момент публикации;
  * фото не генерируются нейросетью и не берутся из Wikimedia — это официальные
    снимки товара с CDN Poizon, уложенные на единый белый холст 1080x1350;
  * цена не "с картинки", а из карточки (минимальная по размерам), проверяется
    повторно прямо перед отправкой;
  * пул товаров и журнал публикаций лежат в sqlite — посты не повторяются.

Команды:
  python bot.py doctor            проверка Telegram + Poizon, ничего не публикует
  python bot.py refill            обновить пул товаров из выдачи Poizon
  python bot.py preview [N]       показать следующий пост (текст + файл), НЕ отправляя
  python bot.py once              опубликовать один пост прямо сейчас
  python bot.py run               включить расписание (долгоживущий процесс)
  python bot.py add <ссылка>      добавить конкретный товар в пул
  python bot.py status            счётчики и последние события
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # dotenv необязателен: можно задать переменные окружения
    def load_dotenv(_path):  # type: ignore
        return False

from imageprep import ImageError, prepare_post_image
from poizon import PoizonClient, PoizonError
from store import Store

ROOT = Path(__file__).resolve().parent
log = logging.getLogger("easybuyer")


# ------------------------------------------------------------------ настройки
def load_config() -> dict:
    load_dotenv(ROOT / ".env")
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    cfg["token"] = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    cfg["channel"] = os.getenv("TELEGRAM_CHANNEL_ID", cfg.get("channel", "")).strip()
    out_dir = ROOT / cfg.get("out_dir", "out")
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg["out_dir"] = str(out_dir)
    db = cfg.get("db_file", "easybuyerpz.sqlite3")
    cfg["db_file"] = db if os.path.isabs(db) else str(ROOT / db)
    times = []
    for item in cfg.get("post_times", []):
        m = re.match(r"^(\d{1,2}):(\d{2})$", str(item).strip())
        if m:
            times.append((int(m.group(1)), int(m.group(2))))
    cfg["post_times"] = times
    return cfg


# ------------------------------------------------------------------ telegram
class Telegram:
    def __init__(self, token: str):
        self.token = token
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, payload: dict | None = None, files: dict | None = None,
             retries: int = 3):
        payload = payload or {}
        last = None
        for attempt in range(1, retries + 1):
            try:
                if files:
                    resp = requests.post(f"{self.base}/{method}", data=payload,
                                         files=files, timeout=90)
                else:
                    resp = requests.post(f"{self.base}/{method}", json=payload, timeout=30)
            except requests.RequestException as exc:
                last = f"сеть: {exc}"
                time.sleep(5 * attempt)
                continue
            try:
                data = resp.json()
            except ValueError:
                last = f"не JSON (HTTP {resp.status_code})"
                time.sleep(3 * attempt)
                continue
            if data.get("ok"):
                return data["result"]
            desc = data.get("description", "unknown")
            last = f"HTTP {resp.status_code}: {desc}"
            params = data.get("parameters") or {}
            if "retry_after" in params:
                wait = min(60, int(params["retry_after"]) + 1)
                log.warning("Telegram rate limit, пауза %s с", wait)
                time.sleep(wait)
            elif resp.status_code == 429:
                time.sleep(10 * attempt)
            elif 400 <= resp.status_code < 500:
                # 4xx (кроме 429) — ошибка запроса/прав, повторять бессмысленно
                raise RuntimeError(f"Telegram {method}: {last}")
            else:
                log.warning("Telegram %s -> %s", method, last)
                time.sleep(4 * attempt)
        raise RuntimeError(f"Telegram {method}: {last}")

    def send_photo(self, chat_id: str, path: str, caption: str) -> int:
        with open(path, "rb") as fh:
            result = self.call("sendPhoto",
                               {"chat_id": chat_id, "caption": caption,
                                "parse_mode": "HTML", "disable_web_page_preview": True},
                               files={"photo": fh})
        return int(result.get("message_id", 0))

    def send_message(self, chat_id: str, text: str) -> int:
        result = self.call("sendMessage",
                           {"chat_id": chat_id, "text": text,
                            "disable_web_page_preview": True})
        return int(result.get("message_id", 0))


# --------------------------------------------------------------------- текст
def escape_html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def make_title(cand, max_chars: int) -> str:
    """Poizon-названия длинные и SEO-насыщенные — делаем аккуратное короткое имя."""
    brand = (cand.brand or "").strip()
    model = (cand.model or "").strip()
    parts = [p for p in (brand, model) if p]
    short = " ".join(dict.fromkeys(parts)).strip()
    title = re.sub(r"\s+", " ", cand.title or "").strip()

    if len(short) >= 8:
        name = short
    else:
        name = title

    if len(name) > max_chars:
        cut = name[:max_chars]
        cut = cut[:cut.rfind(" ")] if " " in cut else cut
        name = cut.rstrip(" ,.-—/")
    return name or title[:max_chars]


def format_price(value: float, cfg: dict) -> str:
    price_cfg = cfg.get("price", {})
    markup = float(price_cfg.get("markup_percent", 0) or 0)
    price = float(value) * (1 + markup / 100.0)
    step = int(price_cfg.get("round_to", 0) or 0)
    if step > 0:
        price = int(round(price / step) * step)
    else:
        price = int(round(price))
    return f"{price:,}".replace(",", " ")


def build_caption(cand, price_str: str, cfg: dict) -> str:
    cap_cfg = cfg.get("caption", {})
    title = make_title(cand, int(cfg.get("filters", {}).get("title_max_chars", 62)))
    template = cap_cfg.get("template") or ["{title}", "", "Цена от {price}₽"]
    lines = []
    for line in template:
        line = line.replace("{title}", title).replace("{price}", price_str)
        line = line.replace("{article}", cand.article or "").replace("{brand}", cand.brand or "")
        line = line.replace("{category}", cand.category or "").replace("{sold}", cand.sold_text or "")
        if "{article}" in line and not cand.article:
            continue
        lines.append(line.rstrip())
    if cap_cfg.get("append_link") and cand.url:
        lines += ["", cand.url]
    tags = cap_cfg.get("append_hashtags") or []
    if tags:
        lines += ["", " ".join(tags)]
    text = "\n".join(lines).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return escape_html(text)


# ------------------------------------------------------------------- пул
def refill_pool(cfg: dict, store: Store, client: PoizonClient) -> int:
    """Достаёт выдачу по кругу: за один проход только несколько запросов из списка,
    чтобы не провоцировать защитный лимит Poizon."""
    src = cfg.get("source", {})
    reqs = src.get("requests", [])
    if not reqs:
        log.warning("в конфиге пустой source.requests")
        return 0
    chunk = max(1, min(int(src.get("requests_per_refill", 3)), len(reqs)))
    idx = int(store.get_state("refill_index", "0") or 0)
    added = 0
    for step in range(chunk):
        req = reqs[(idx + step) % len(reqs)]
        kind, value = req.get("kind", "search"), req.get("value", "")
        if not value:
            continue
        log.info("загрузка выдачи: %s %s", kind, value)
        try:
            products = client.listing(kind, value, pages=int(src.get("pages_per_request", 1)))
        except PoizonError as exc:
            log.warning("не удалось получить %s %s: %s", kind, value, exc)
            store.log("warn", f"refill fail {kind}:{value} — {exc}")
            continue
        for prod in products:
            if not prod.all_images():
                continue
            if not prod.price:
                continue
            store.upsert_product(prod)
            added += 1
    store.set_state("refill_index", str((idx + chunk) % len(reqs)))
    store.log("info", f"refill: обновлено {added} товаров (запросы {idx + 1}-{idx + chunk} из {len(reqs)})")
    log.info("пул обновлён: %s позиций", added)
    return added


def verify_price(cfg: dict, store: Store, client: PoizonClient, cand) -> float | None:
    """Перед публикацией перечитываем цену со страницы товара."""
    price_cfg = cfg.get("price", {})
    if not price_cfg.get("verify_before_publish", True):
        return cand.price
    try:
        prod = client.by_url(cand.url)
        new_price = prod.price
    except PoizonError as exc:
        log.warning("цену проверить не удалось (%s) — публикуем сохранённую", exc)
        store.log("warn", f"price verify fail spu={cand.spu_id}: {exc}")
        return cand.price
    # заодно подтягиваем с карточки короткое имя (бренд+модель) и артикул
    cand.model = getattr(prod, "model", "") or cand.model
    cand.color = getattr(prod, "color", "") or cand.color
    cand.article = getattr(prod, "article", "") or cand.article
    if not new_price:
        return cand.price
    if cand.price and cand.price > 0:
        diff = abs(new_price - cand.price) / cand.price * 100
        limit = float(price_cfg.get("max_change_percent", 15))
        if diff > limit:
            log.info("цена изменилась: %.0f -> %.0f (%.1f%%)", cand.price, new_price, diff)
            store.log("info", f"price change spu={cand.spu_id}: {cand.price} -> {new_price}")
    cand.price = new_price
    store.upsert_product(prod)
    return new_price


# --------------------------------------------------------------- публикация
def publish_once(cfg: dict, store: Store, client: PoizonClient,
                 tg: Telegram | None, dry_run: bool = False) -> bool:
    filters = cfg.get("filters", {})
    image_cfg = cfg.get("image", {})
    candidates = store.candidates(
        min_price=filters.get("min_price"),
        max_price=filters.get("max_price"),
        exclude_words=filters.get("exclude_words") or [],
        no_repost_days=int(filters.get("no_repost_days", 30)),
        limit=80,
    )
    if not candidates:
        log.warning("в пуле нет свободных товаров — нужен refill")
        notify(cfg, store, tg, "Пост не опубликован: пул пуст. Нужен refill.")
        return False
    random.shuffle(candidates)

    attempts = 0
    for cand in candidates:
        attempts += 1
        if attempts > 8:
            break
        price = verify_price(cfg, store, client, cand)
        if not price:
            continue
        price_str = format_price(price, cfg)
        caption = build_caption(cand, price_str, cfg)

        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        out_path = str(Path(cfg["out_dir"]) / f"post_{stamp}_{cand.spu_id}.jpg")
        try:
            prepared = prepare_post_image(
                cand.images(), out_path,
                canvas=tuple(image_cfg.get("canvas", [1080, 1350])),
                padding_percent=int(image_cfg.get("padding_percent", 12)),
                quality=int(image_cfg.get("quality", 90)),
                photos_per_post=int(image_cfg.get("photos_per_post", 1)),
                require_white=bool(filters.get("require_white_background", True)),
                remove_bg=bool(image_cfg.get("remove_background", False)),
                salt=f"{cand.spu_id}-{stamp}-{price_str}",
            )
        except ImageError as exc:
            log.info("пропуск spu=%s: %s", cand.spu_id, exc)
            store.log("warn", f"image skip spu={cand.spu_id}: {exc}")
            continue

        if dry_run or not tg:
            print("\n--- ПРЕДПРОСМОТР (не отправлено) ---")
            print(f"товар : {make_title(cand, 80)}  [{cand.article}]")
            print(f"цена  : {price_str} ₽  (poizon: {cand.price_text or price})")
            print(f"фото  : {prepared.path}  {prepared.width}x{prepared.height}")
            print(f"источник: {cand.url}")
            print("\n--- подпись ---")
            print(re.sub(r"<[^>]+>", "", caption))
            return True

        try:
            msg_id = tg.send_photo(cfg["channel"], prepared.path, caption)
        except RuntimeError as exc:
            log.error("sendPhoto не удался: %s", exc)
            store.log("error", f"sendPhoto fail spu={cand.spu_id}: {exc}")
            notify(cfg, store, tg, f"Не удалось опубликовать пост: {exc}")
            return False

        store.mark_posted(cand.spu_id, price, make_title(cand, 80), msg_id, prepared.path)
        store.log("info", f"posted spu={cand.spu_id} price={price} msg={msg_id}")
        log.info("ОПУБЛИКОВАНО: %s | %s ₽ | msg %s", make_title(cand, 60), price_str, msg_id)
        if cfg.get("notify", {}).get("notify_on_publish"):
            notify(cfg, store, tg, f"Пост опубликован: {make_title(cand, 60)} — {price_str} ₽")
        return True

    notify(cfg, store, tg, "Не нашёл товар с подходящим фото/ценой. Нужен refill.")
    return False


def notify(cfg: dict, store: Store, tg: Telegram | None, text: str) -> None:
    store.log("notify", text)
    notify_cfg = cfg.get("notify", {})
    chat = (notify_cfg.get("admin_chat") or "").strip()
    if not chat or not tg or not notify_cfg.get("notify_on_error", True):
        return
    try:
        tg.send_message(chat, f"[EasyBuyer] {text}")
    except RuntimeError as exc:
        log.warning("не удалось уведомить админа: %s", exc)


# -------------------------------------------------------------- запуск/цикл
def scheduler_run(cfg: dict, store: Store, client: PoizonClient, tg: Telegram) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    tz_name = cfg.get("timezone", "Europe/Moscow")
    tz = ZoneInfo(tz_name)
    sched = BlockingScheduler(timezone=tz)

    for hour, minute in cfg["post_times"]:
        sched.add_job(
            publish_once, CronTrigger(hour=hour, minute=minute, timezone=tz),
            args=(cfg, store, client, tg), id=f"post_{hour:02d}{minute:02d}",
            max_instances=1, coalesce=True, misfire_grace_time=14400,
        )
    refresh_hours = int(cfg.get("source", {}).get("refresh_hours", 6))
    sched.add_job(refill_pool, "interval", hours=refresh_hours,
                  args=(cfg, store, client), id="refill",
                  max_instances=1, coalesce=True, misfire_grace_time=600)

    times = ", ".join(f"{h:02d}:{m:02d}" for h, m in cfg["post_times"])
    log.info("EasyBuyer Poizon: канал %s, расписание %s (%s)", cfg["channel"], times, tz_name)

    # Предварительная загрузка POIZON отключена.
    sched.start()


def main() -> int:
    parser = argparse.ArgumentParser(description="EasyBuyer Poizon bot")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "once", "preview", "refill", "doctor", "status", "add"])
    parser.add_argument("arg", nargs="?", default="", help="ссылка на товар для add")
    parser.add_argument("--dry-run", action="store_true", help="не отправлять в Telegram")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s",
                        stream=sys.stdout)

    cfg = load_config()
    store = Store(cfg["db_file"])
    src_cfg = cfg.get("source", {})
    delay = tuple(src_cfg.get("request_delay_seconds", [2.5, 5.0]))
    client = PoizonClient(src_cfg.get("base_url", "https://www.thepoizon.ru"),
                          delay=delay,
                          block_cooldown_minutes=int(src_cfg.get("block_cooldown_minutes", 45)))
    try:  # кулдаун переживает перезапуск процесса
        client.blocked_until = float(store.get_state("blocked_until", "0") or 0)
    except ValueError:
        pass
    client.on_block = lambda ts: store.set_state("blocked_until", str(ts))
    tg = Telegram(cfg["token"]) if cfg["token"] else None
    dry = args.dry_run or cfg.get("dry_run", False) or not tg

    if args.command == "doctor":
        until = float(store.get_state("blocked_until", "0") or 0)
        print("Telegram:", end=" ")
        if tg:
            me = tg.call("getMe")
            chat = tg.call("getChat", {"chat_id": cfg["channel"]})
            print(f"@{me.get('username')} -> {chat.get('title', cfg['channel'])}")
        else:
            print("нет токена (задайте TELEGRAM_BOT_TOKEN в .env)")
        if until > time.time():
            print(f"Poizon: кулдаун после лимита, ещё {int(until - time.time())} с "
                  f"(можно подождать и повторить)")
        print("Poizon:", end=" ")
        try:
            prods = client.listing("search", "nike air force 1", pages=1)
            if not prods:
                print("выдача пустая — см. сообщения выше")
            for p in prods[:3]:
                print(f"\n  {p.title[:70]} | {p.price_text} | {p.main_image[:70]}")
        except PoizonError as exc:
            print(f"ошибка: {exc}")
        print("\nПроверка завершена, в Telegram ничего не отправлено.")
        return 0

    if args.command == "refill":
        refill_pool(cfg, store, client)
        print(json.dumps(store.counts(), ensure_ascii=False))
        return 0

    if args.command == "status":
        stats = store.counts()
        until = float(store.get_state("blocked_until", "0") or 0)
        if until > time.time():
            stats["poizon_cooldown_left_s"] = int(until - time.time())
        stats["refill_index"] = store.get_state("refill_index", "0")
        print(json.dumps(stats, ensure_ascii=False, indent=1))
        for ev in store.recent_events(12):
            print(f"  {ev['ts']} {ev['level']:7} {ev['text']}")
        return 0

    if args.command == "add":
        if not args.arg:
            print("нужна ссылка: python bot.py add https://www.thepoizon.ru/product/...")
            return 2
        prod = client.by_url(args.arg)
        store.upsert_product(prod)
        print(f"добавлен: {prod.title[:80]} | {prod.price_text} | фото: {len(prod.all_images())}")
        return 0

    if args.command == "preview":
        ok = publish_once(cfg, store, client, None, dry_run=True)
        return 0 if ok else 1

    if args.command == "once":
        if not tg:
            print("Нет TELEGRAM_BOT_TOKEN — используйте preview или пропишите токен в .env")
            return 2
        return 0 if publish_once(cfg, store, client, tg) else 1

    # run
    if not tg:
        print("Нет TELEGRAM_BOT_TOKEN — расписание не запускается.")
        return 2
    try:
        scheduler_run(cfg, store, client, tg)
    except (KeyboardInterrupt, SystemExit):
        log.info("остановлено вручную")
    return 0


if __name__ == "__main__":
    sys.exit(main())
