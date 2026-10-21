
import io
import os
import re

import requests
from PIL import Image, ImageOps

from product_finder import PRODUCTS, find_images


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
            "— найдено меньше 3 фотографий",
        )
        return None

    selected = images[:3]
    columns = 3
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
