
import requests

API_URL = "https://commons.wikimedia.org/w/api.php"

HEADERS = {
    "User-Agent": "EasyBuyerCloud/0.6 (Telegram: @easybuyerpz)"
}

PRODUCTS = [
    {
        "name": "Nike Air Force 1",
        "query": "Nike Air Force 1",
        "keywords": ["nike", "air", "force"],
    },
    {
        "name": "Adidas Samba",
        "query": "Adidas Samba",
        "keywords": ["adidas", "samba"],
    },
    {
        "name": "New Balance 530",
        "query": "New Balance 530",
        "keywords": ["new", "balance", "530"],
    },
    {
        "name": "Timberland 6 Inch",
        "query": "Timberland 6 inch boots",
        "keywords": ["timberland"],
    },
]

ALLOWED_LICENSES = {
    "CC0",
    "CC BY 4.0",
    "CC BY-SA 4.0",
    "Public domain",
}


def find_images(product):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": product["query"],
        "gsrnamespace": 6,
        "gsrlimit": 20,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 600,
        "format": "json",
    }

    response = requests.get(
        API_URL,
        params=params,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    data = response.json()
    pages = data.get("query", {}).get("pages", {})

    matches = []

    for page in pages.values():
        title = page.get("title", "")
        title_lower = title.lower()

        if not all(
            word in title_lower
            for word in product["keywords"]
        ):
            continue

        info_list = page.get("imageinfo", [])

        if not info_list:
            continue

        info = info_list[0]
        metadata = info.get("extmetadata", {})

        license_name = metadata.get(
            "LicenseShortName", {}
        ).get("value", "Unknown")

        if license_name not in ALLOWED_LICENSES:
            continue

        image_url = info.get("thumburl")

        if not image_url:
            continue

        matches.append({
            "title": title,
            "image_url": image_url,
            "original_url": info.get("url", ""),
            "description_url": info.get("descriptionurl", ""),
            "license": license_name,
            "license_url": metadata.get(
                "LicenseUrl", {}
            ).get("value", ""),
            "artist": metadata.get(
                "Artist", {}
            ).get("value", ""),
        })

    return matches


def main():
    print("EasyBuyer: поиск уменьшенных фотографий")
    print("--------------------------------------")

    for product in PRODUCTS:
        print("\nМОДЕЛЬ:", product["name"])

        try:
            images = find_images(product)

            print("Найдено фото:", len(images))

            for item in images[:3]:
                print("Фото:", item["title"])
                print("Ссылка:", item["image_url"])
                print("Лицензия:", item["license"])
                print("---")

        except requests.RequestException as error:
            print("Ошибка сети:", error)

    print("\nТЕСТ ЗАВЕРШЁН. В Telegram ничего не отправлено.")


if __name__ == "__main__":
    main()
