
import re
import requests
from html.parser import HTMLParser

URL = (
    "https://www.thepoizon.ru/product/"
    "hourglass-eye-shadows-women-s-8900370567806882"
    "?skuid=8906349994636882"
)

class ProductParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta = {}
        self.images = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "meta":
            key = attrs.get("property") or attrs.get("name")
            if key in ("og:title", "og:image", "description",
                       "product:price:amount"):
                self.meta[key] = attrs.get("content", "")
        if tag == "img":
            src = attrs.get("src") or attrs.get("data-src")
            if src:
                self.images.append(src)

try:
    response = requests.get(URL, timeout=25)
    print("STATUS:", response.status_code)
    print("HTML:", len(response.text))

    parser = ProductParser()
    parser.feed(response.text)

    print("META:", parser.meta)
    print("IMAGE COUNT:", len(parser.images))
    print("IMAGES:", parser.images[:5])
    print("SKU FOUND:", "8906349994636882" in response.text)
    print(
        "PRICE FOUND:",
        bool(re.search(r"13[\s\u00a0\u202f]*052|13052", response.text))
    )
    print("TEST COMPLETE: nothing published")

except requests.RequestException as error:
    print("ERROR:", error)

python test_thepoizon.py
