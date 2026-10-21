"""Безопасная диагностика публичной карточки poizon.ru.

Запуск: python test_poizon.py
Ничего не публикует и не скачивает фотографии.
"""
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import requests

URL = 'https://poizon.ru/product/jr0861'


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = []
        self.images = []
        self.scripts = []
        self._json_script = False
        self._parts = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta.append(attrs)
        elif tag == 'img':
            self.images.append(attrs)
        elif tag == 'script' and attrs.get('type') == 'application/ld+json':
            self._json_script = True
            self._parts = []

    def handle_data(self, data):
        if self._json_script:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._json_script:
            self.scripts.append(''.join(self._parts))
            self._json_script = False


def main():
    print('Проверяем:', URL)
    try:
        response = requests.get(
            URL,
            headers={'User-Agent': 'EasyBuyerDiagnostics/1.0 (public-page-check)'},
            timeout=20,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        print('Ошибка соединения:', exc)
        return

    print('HTTP-статус:', response.status_code)
    print('Итоговый адрес:', response.url)
    print('Тип ответа:', response.headers.get('Content-Type', 'не указан'))
    if response.status_code != 200:
        print('Страница не вернула HTTP 200. Автоматическое получение данных не подтверждено.')
        return

    if 'html' not in response.headers.get('Content-Type', '').lower():
        print('Ответ не похож на HTML.')
        return

    parser = PageParser()
    parser.feed(response.text)
    metadata = {}
    for item in parser.meta:
        key = item.get('property') or item.get('name')
        if key in ('og:title', 'og:image', 'product:price:amount', 'description'):
            metadata[key] = unescape(item.get('content', ''))

    print('\nПубличные метаданные:')
    print(json.dumps(metadata, ensure_ascii=False, indent=2))

    print('\nСтруктурированные данные JSON-LD:')
    if parser.scripts:
        for raw in parser.scripts[:3]:
            try:
                data = json.loads(raw)
                print(json.dumps(data, ensure_ascii=False, indent=2)[:2500])
            except json.JSONDecodeError:
                print('Обнаружен JSON-LD, но разобрать его не удалось.')
    else:
        print('Не найдены.')

    image_urls = []
    for img in parser.images:
        for key in ('src', 'data-src'):
            value = img.get(key, '')
            if value.startswith(('https://', 'http://', '/')):
                candidate = urljoin(response.url, value)
                if urlparse(candidate).scheme in ('http', 'https') and candidate not in image_urls:
                    image_urls.append(candidate)

    print('\nАдреса изображений из HTML (первые 10, без скачивания):')
    if image_urls:
        for link in image_urls[:10]:
            print('-', link)
    else:
        print('Не найдены.')

    print('\nПроверка завершена. Наличие ссылок не подтверждает, что это фото товара JR0861,')
    print('и не даёт разрешения на коммерческое использование изображений.')


if __name__ == '__main__':
    main()
