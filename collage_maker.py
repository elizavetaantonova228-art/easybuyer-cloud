
import io
import os
import re

import requests
from PIL import Image, ImageOps

from product_finder import PRODUCTS, find_images
import io
import os
import re
import time

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

from product_finder import PRODUCTS, find_images


OUTPUT_DIR = "collages"
CELL_SIZE = (600, 600)
BACKGROUND = "white"

HEADERS = {
    "User-Agent": "EasyBuyerCloud/0.4 (Telegram: @easybuyerpz)"
}


def safe_filename(text):
    return re.sub(
        r"[^a-zA-Z0-9_-]+", "_", text
    ).strip("_")


def download_image(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )

    if response.status_code == 429:
        print("Wikimedia ограничила загрузку (429). Пропускаем фото.")
        return None

    response.raise_for_status()

    try:
        image = Image.open(io.BytesIO(response.content))
        image.load()
        return image.convert("RGB")
    except UnidentifiedImageError:
        print("Полученный файл не является изображением.")
        return None


def prepare_image(image):
    return ImageOps.contain(
        image,
        CELL_SIZE,
        method=Image.Resampling.LANCZOS,
    )


def create_collage(images, product_name):
    if not images:
        print("Пропуск:", product_name, "— фотографии не найдены")
        return None

    selected = images[:3]
    prepared = []

    for item in selected:
        try:
            image = download_image(item["image_url"])

            if image is not None:
                prepared.append(prepare_image(image))

        except requests.RequestException as error:
            print("Не удалось загрузить фотографию:", error)
        except (OSError, ValueError) as error:
            print("Ошибка обработки изображения:", error)

        time.sleep(1)

    if not prepared:
        print("Пропуск:", product_name, "— фото не загрузились")
        return None

    columns = len(prepared)
    collage = Image.new(
        "RGB",
        (columns * CELL_SIZE[0], CELL_SIZE[1]),
        BACKGROUND,
    )

    for index, image in enumerate(prepared):
        x = index * CELL_SIZE[0]
        x += (CELL_SIZE[0] - image.width) // 2
        y = (CELL_SIZE[1] - image.height) // 2

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
            print("Найдено фотографий:", len(images))

            path = create_collage(images, name)

            if path:
                print("Коллаж сохранён:", path)

        except requests.RequestException as error:
            print("Ошибка сети:", error)
        except Exception as error:
            print("Ошибка обработки товара:", error)

    print("\nТЕСТ ЗАВЕРШЁН. В Telegram ничего не отправлено.")


if __name__ == "__main__":
    main()



OUTPUT_DIR = "collages"
CELL_SIZE = (600, 600)
BACKGROUND = "white"

HEADERS = {
    "User-Agent": "EasyBuyerCloud/0.3 (Telegram @easybuyerpz)"
}


def safe_filename(text):
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_")


def download_image(url):
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    image = Image.open(io.BytesIO(response.content))
    return image.convert("RGB")


def prepare_image(image):
    return ImageOps.contain(
        image,
        CELL_SIZE,
        method=Image.Resampling.LANCZOS,
    )


def create_collage(images, product_name):
    if len(images) < 1:
        print(
            "Пропуск:",
            product_name,
"— фотографии не найдены",
        )
        return None

    selected = images[:3]
columns = len(selected)
    rows = (len(selected) + columns - 1) // columns

    collage = Image.new(
        "RGB",
        (columns * 600, rows * 600),
        BACKGROUND,
    )

    successful = 0

    for item in selected:
        try:
            image = download_image(item["image_url"])
            image = prepare_image(image)

            x = (successful % columns) * 600
            y = (successful // columns) * 600

            x += (600 - image.width) // 2
            y += (600 - image.height) // 2

            collage.paste(image, (x, y))
            successful += 1

        except Exception as error:
            print("Не удалось загрузить фото:", error)

    if successful < 1:
        print("Недостаточно загруженных фотографий")
        return None

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    filename = safe_filename(product_name) + ".jpg"
    path = os.path.join(OUTPUT_DIR, filename)

    collage.save(path, quality=92)
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

        except Exception as error:
            print("Ошибка:", error)

    print("\nГОТОВО. В Telegram ничего не отправлено.")


if __name__ == "__main__":
    main()
