
import requests

API_URL = "https://commons.wikimedia.org/w/api.php"

SEARCH_TERMS = [
    "Nike Air Force 1 sneakers",
    "Adidas Samba shoes",
    "New Balance 530 shoes",
    "Timberland boots",
]


def search_images(query, limit=8):
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": f'filetype:bitmap "{query}"',
        "gsrnamespace": 6,
        "gsrlimit": limit,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "format": "json",
    }

    response = requests.get(
        API_URL,
        params=params,
        headers={
            "User-Agent": "EasyBuyerCloud/0.1 (Telegram: @easybuyerpz)"
        },
        timeout=25,
    )
    response.raise_for_status()

    pages = response.json().get("query", {}).get("pages", {})
    results = []

    for page in pages.values():
        info = page.get("imageinfo", [{}])[0]
        metadata = info.get("extmetadata", {})

        license_name = metadata.get(
            "LicenseShortName", {}
        ).get("value", "Unknown")

        license_url = metadata.get(
            "LicenseUrl", {}
        ).get("value", "")

        image_url = info.get("url")

        if image_url:
            results.append({
                "title": page.get("title", ""),
                "image_url": image_url,
                "license": license_name,
                "license_url": license_url,
            })

    return results


def main():
    print("EasyBuyer: поиск фотографий товаров")
    print("---------------------------------")

    for product in SEARCH_TERMS:
        print(f"\nТОВАР: {product}")

        try:
            images = search_images(product)

            if not images:
                print("Фотографии не найдены")
                continue

            for image in images[:5]:
                print("Название:", image["title"])
                print("Фото:", image["image_url"])
                print("Лицензия:", image["license"])
                print("Условия:", image["license_url"])
                print("---")

        except requests.RequestException as error:
            print("Ошибка поиска:", error)

    print("\nТЕСТ ЗАВЕРШЁН. Ничего не опубликовано.")


if __name__ == "__main__":
    main()
