
import requests

API_URL = "https://commons.wikimedia.org/w/api.php"

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
        "gsrlimit": 30,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "format": "json",
    }

    response = requests.get(
        API_URL,
        params=params,
        headers={
            "User-Agent": "EasyBuyerCloud/0.2 (Telegram @easybuyerpz)"
        },
        timeout=25,
    )
    response.raise_for_status()

    pages = response.json().get("query", {}).get("pages", {})
    matches = []

    for page in pages.values():
        title = page.get("title", "").lower()

        if not all(
            word in title for word in product["keywords"]
        ):
            continue

        info = page.get("imageinfo", [{}])[0]
        metadata = info.get("extmetadata", {})

        license_name = metadata.get(
            "LicenseShortName", {}
        ).get("value", "Unknown")

        if license_name not in ALLOWED_LICENSES:
            continue

        image_url = info.get("url")

        if not image_url:
            continue

        matches.append({
            "title": page["title"],
            "image_url": image_url,
            "license": license_name,
            "license_url": metadata.get(
                "LicenseUrl", {}
            ).get("value", ""),
        })

    return matches


def main():
    print("EasyBuyer: точный поиск моделей")
    print("--------------------------------")

    for product in PRODUCTS:
        print("\nМОДЕЛЬ:", product["name"])

        try:
            images = find_images(product)

            if not images:
                print("Подходящие фотографии не найдены")
                continue

            for image in images[:5]:
                print("Фото:", image["title"])
                print("Ссылка:", image["image_url"])
                print("Лицензия:", image["license"])
                print("---")

        except requests.RequestException as error:
            print("Ошибка:", error)

    print("\nТЕСТ ЗАВЕРШЁН. Ничего не опубликовано.")


if __name__ == "__main__":
    main()
