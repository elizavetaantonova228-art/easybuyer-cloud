import json
import logging
import os
import random
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from apscheduler.schedulers.blocking import BlockingScheduler
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / '.env')
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
CHANNEL = os.getenv('TELEGRAM_CHANNEL_ID', '@easybuyerpz').strip()
TZ = os.getenv('TIMEZONE', 'Europe/Moscow').strip()
TIMES = [(9, 0), (12, 30), (16, 0), (19, 30)]
STATE = ROOT / 'posted_state.json'

POSTS = [
    '👗 5 вещей, которые легко сочетать между собой\n\nПрямые джинсы, белая рубашка, однотонный жакет, лоферы и лаконичная сумка — основа множества повседневных образов.\n\nСохраняйте идею для следующего выхода!\n\n#EasyBuyer #Стиль',
    '✨ Как сделать базовый образ интереснее?\n\nДобавьте один акцент: ремень, яркий платок или серьги необычной формы. Необязательно менять весь гардероб, чтобы освежить привычное сочетание.\n\n#EasyBuyer #Мода',
    '🧥 Жакет вне офиса\n\nПопробуйте сочетать свободный жакет с футболкой, джинсами и кедами. Получится комфортный образ на каждый день.\n\n#EasyBuyer #Образы',
    '🎨 Простая цветовая формула\n\nВыберите два нейтральных оттенка и один акцентный. Например: молочный + графитовый + бордовый. Так комплект выглядит собранно без сложных правил.\n\n#EasyBuyer #Стиль',
    '👖 Как выбрать универсальные джинсы?\n\nОбратите внимание на посадку, комфорт в движении и то, как джинсы сочетаются с вашей обувью. Самая удачная модель — та, которую хочется носить часто.\n\n#EasyBuyer #Гардероб',
    '👜 Одна сумка — много образов\n\nЛаконичная сумка среднего размера может дополнить и джинсы с рубашкой, и платье. При выборе проверьте удобство ручек и вместительность.\n\n#EasyBuyer #Аксессуары',
    '👟 Удобство тоже часть стиля\n\nКеды с прямыми брюками, лоферы с джинсами, ботильоны с юбкой миди — сочетайте привычные вещи по-новому.\n\n#EasyBuyer #Образы',
    '🧶 Многослойность без лишнего объёма\n\nТонкий трикотаж, рубашка и свободный верхний слой помогут адаптировать образ к переменчивой погоде. Оставляйте немного пространства между слоями.\n\n#EasyBuyer #Советы',
    '🤍 Белая рубашка: три идеи\n\nНосите её с джинсами, поверх майки как лёгкий слой или заправленной в широкие брюки. Один предмет — несколько настроений.\n\n#EasyBuyer #Гардероб',
    '🌿 Осознанные покупки\n\nПеред покупкой спросите себя: с какими тремя вещами из моего гардероба это будет сочетаться? Такой вопрос помогает выбирать одежду практичнее.\n\n#EasyBuyer #Шопинг',
    '🖤 Монохромный образ\n\nСочетайте разные фактуры в одном цвете: например, гладкую рубашку, трикотаж и деним. Так комплект будет выглядеть интереснее.\n\n#EasyBuyer #Стиль',
    '🧣 Маленькая деталь — новый образ\n\nПлаток можно повязать на шею, ручку сумки или использовать как акцент в причёске. Выбирайте вариант, который удобен именно вам.\n\n#EasyBuyer #Аксессуары',
    '👗 Платье на каждый день\n\nПопробуйте сочетать простое платье с кардиганом и удобной обувью. А вечером смените аксессуары — и настроение образа изменится.\n\n#EasyBuyer #Образы',
    '🧥 Как выбирать верхнюю одежду\n\nПримеряйте её поверх самого объёмного слоя, который планируете носить. Проверьте свободу движений в плечах и рукавах.\n\n#EasyBuyer #Советы',
    '💫 Правило одной выразительной детали\n\nЕсли выбрали яркую обувь или необычную сумку, остальную часть комплекта можно сделать спокойнее. Это простой способ собрать гармоничный образ.\n\n#EasyBuyer #Стиль',
    '📌 Мини-ревизия гардероба\n\nОтложите вещи, которые не носили давно, и попробуйте составить с ними три новых комплекта. Иногда свежие идеи уже висят в шкафу.\n\n#EasyBuyer #Гардероб',
]

def telegram(method, payload=None):
    if not TOKEN:
        raise RuntimeError('Не задан TELEGRAM_BOT_TOKEN. Добавьте его в переменные окружения хостинга.')
    r = requests.post(f'https://api.telegram.org/bot{TOKEN}/{method}', json=payload or {}, timeout=30)
    r.raise_for_status()
    data = r.json()
    if not data.get('ok'):
        raise RuntimeError(f'Telegram: {data.get("description", "неизвестная ошибка")}')
    return data['result']

def choose_post():
    used = []
    if STATE.exists():
        try:
            used = json.loads(STATE.read_text(encoding='utf-8')).get('used', [])
        except (OSError, ValueError):
            logging.warning('Не удалось прочитать историю публикаций')
    available = [i for i in range(len(POSTS)) if i not in used]
    if not available:
        used = []
        available = list(range(len(POSTS)))
    index = random.choice(available)
    return index, used, POSTS[index]

def publish():
    index, used, post = choose_post()
    telegram('sendMessage', {'chat_id': CHANNEL, 'text': post})
    STATE.write_text(json.dumps({'used': used + [index]}, ensure_ascii=False), encoding='utf-8')
    logging.info('Пост отправлен в %s', CHANNEL)

def main():
    import sys
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    command = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if command == 'preview':
        print('\n--- ПРЕДПРОСМОТР: НЕ ОТПРАВЛЕНО ---\n')
        print(choose_post()[2])
    elif command == 'check':
        bot = telegram('getMe')
        chat = telegram('getChat', {'chat_id': CHANNEL})
        print(f'Telegram OK: @{bot.get("username", "")} -> {chat.get("title", CHANNEL)}')
    elif command == 'publish':
        publish()
    elif command == 'run':
        if not TOKEN:
            raise RuntimeError('Сначала задайте TELEGRAM_BOT_TOKEN в переменных окружения')
        scheduler = BlockingScheduler(timezone=ZoneInfo(TZ))
        for hour, minute in TIMES:
            scheduler.add_job(publish, 'cron', hour=hour, minute=minute, id=f'post_{hour:02d}{minute:02d}', max_instances=1, coalesce=True, misfire_grace_time=120)
        logging.info('EasyBuyer Cloud: %s; %s', TZ, ', '.join(f'{h:02d}:{m:02d}' for h, m in TIMES))
        scheduler.start()
    else:
        raise SystemExit('Используйте: python bot.py preview|check|publish|run')

if __name__ == '__main__':
    main()
