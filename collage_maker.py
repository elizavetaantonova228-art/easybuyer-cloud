
import io
import os
import re

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from product_finder import PRODUCTS, find_images


OUTPUT_DIR = "collages"
CELL_SIZE = 600

HEADERS = {
    "User-Agent": "EasyBuyerCloud/0.5 (Telegram: @easybuyerpz)"
}


def safe_filename(text):
    return re.sub(
        r"[^a-zA-Z0-9_-]+", "_", text
    ).strip("_")


def download_image(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=25,
        )

        if response.status_code == 429:
            print("Лимит Wikimedia (429). Фото пропущено.")
            return None

        response.raise_for_status()

        image = Image.open(io.BytesIO(response.content))
        image.load()
        return image.convert("RGB")

    except (
        requests.RequestException,
        UnidentifiedImageError,
        OSError,
    ) as error:
        print("Ошибка загрузки фотографии:", error)
        return None


def create_collage(images, product_name):
    if not images:
        print("Пропуск: фотографии не найдены")
        return None

    prepared = []

    for item in images[:3]:
        image = download_image(item["image_url"])

        if image is not None:
            image = ImageOps.contain(
                image,
                (CELL_SIZE, CELL_SIZE),
                method=Image.Resampling.LANCZOS,
            )
            prepared.append(image)

    if not prepared:
        print("Пропуск: ни одно фото не загрузилось")
        return None

    columns = len(prepared)

    collage = Image.new(
        "RGB",
        (CELL_SIZE * columns, CELL_SIZE),
        "white",
    )

    for index, image in enumerate(prepared):
        x = index * CELL_SIZE
        x += (CELL_SIZE - image.width) // 2
        y = (CELL_SIZE - image.height) // 2

        collage.paste(image, (x, y))

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    filename = safe_filename(product_name) + ".jpg"
    path = os.path.join(OUTPUT_DIR, filename)

    collage.save(path, format="JPEG", quality=92)

    return path


def main():
    print("EasyBuyer: создание коллажей")
    print("----------------------------")

    for product in PRODUCTS:
        name = product["name"]
        print("\nТовар:", name)

        try:
            images = find_images(product)
            print("Найдено фото:", len(images))

            path = create_collage(images, name)

            if path:
                print("Коллаж сохранён:", path)

        except requests.RequestException as error:
            print("Ошибка поиска:", error)

    print("\nТЕСТ ЗАВЕРШЁН. В Telegram ничего не отправлено.")


if __name__ == "__main__":
    main()
