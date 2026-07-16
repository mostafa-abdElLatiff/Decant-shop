#!/usr/bin/env python3
"""
sync_mo_shawky.py — sync MO Shawky's Odoo-based decant shop into
products.json. No AI/vision involved: the shop is server-rendered HTML
(Odoo doesn't expose a public JSON product API the way Shopify does), so
this parses the product grid pages directly with regex.

How this store works, since it's the trickiest of the three sites so far:
each *size* of a fragrance (3ML/5ML/10ML) is its own separate, independent
product listing in Odoo — not one product with a size dropdown. Some
fragrances are only listed at one size, others at a different size; there's
no guaranteed 3/5/10ml set per fragrance. So each scraped card becomes one
product with exactly one decant offer at whatever size/price it's listed
at — no grouping needed. The shop's own listing only shows what's currently
sellable (no explicit "sold out" state was found in the HTML), so scraping
the listing pages already gives you in-stock items only.

Run whenever you want to refresh this store's listings:

    python sync_mo_shawky.py

Commits locally if anything changed — never pushes. Review with
`git log` / `git diff` and push yourself when ready.
"""
import html
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import slugify, find_existing_product, unique_id_for, track_offer, CATALOG  # noqa: E402
from brand_prefixes import split_brand_prefix  # noqa: E402

BASE_URL = "https://z-original-perfumes-decant.odoo.com"
SHOP_PATH = "/shop?tags=62,63"
STORE_NAME = "MO Shawky"
STORE_URL = "https://www.facebook.com/mo.freeto.play/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"


def fetch(path: str) -> str:
    req = urllib.request.Request(f"{BASE_URL}{path}", headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def total_pages(html: str) -> int:
    nums = [int(n) for n in re.findall(r"/shop/page/(\d+)\?tags=", html)]
    return max(nums) if nums else 1


def parse_cards(html: str) -> list:
    blocks = re.split(r'(?=<form role="article" class="oe_product_cart)', html)
    items = []
    for b in blocks[1:]:
        title_m = re.search(r'aria-label="([^"]+)"', b)
        img_m = re.search(r'<img src="([^"]+)"', b)
        price_m = re.search(r'oe_currency_value">([\d.]+)</span>\s*LE', b)
        href_m = re.search(r'href="(/shop/[^"]+)"', b)
        if title_m and price_m:
            items.append({
                "title": title_m.group(1).strip(),
                "price": float(price_m.group(1)),
                "image": img_m.group(1) if img_m else "",
                "product_url": f"{BASE_URL}{href_m.group(1)}" if href_m else None,
            })
    return items


def split_brand(name_and_size: str):
    """Strip the trailing size, then split a leading known brand off the name."""
    name_and_size = re.sub(r"\s+", " ", html.unescape(name_and_size)).strip()
    m = re.match(r"^(.*?)[\s-]+(\d+)\s*ML\s*$", name_and_size, re.I)
    if not m:
        return None
    name, ml = m.group(1).strip(), int(m.group(2))
    name_en, brand = split_brand_prefix(name)
    return {"name_en": name_en, "brand": brand, "ml": ml}


def download_image(url, dest_path):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest_path.write_bytes(resp.read())


def main():
    print(f"Fetching {BASE_URL}{SHOP_PATH} ...")
    first = fetch(SHOP_PATH)
    pages = total_pages(first)
    print(f"  {pages} page(s)")

    cards = parse_cards(first)
    for p in range(2, pages + 1):
        html = fetch(f"/shop/page/{p}?tags=62,63")
        cards.extend(parse_cards(html))
    print(f"  {len(cards)} listings")

    parsed = []
    for c in cards:
        info = split_brand(c["title"])
        if not info or not info["name_en"]:
            print(f"  skip (couldn't parse size): {c['title']!r}")
            continue
        info["image"] = c["image"]
        info["price"] = int(c["price"])
        info["product_url"] = c["product_url"]
        parsed.append(info)

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}
    IMAGES_DIR.mkdir(exist_ok=True)
    added, synced = 0, 0

    for info in parsed:
        product = find_existing_product(catalog, info["name_en"], info["brand"])
        if product is None:
            product = {
                "id": unique_id_for(catalog, info["name_en"], info["brand"]),
                "name_ar": "",
                "name_en": info["name_en"],
                "brand": info["brand"],
                "dupe_of": [],
                "image": "",
                "accords": [],
                "stores": [],
            }
            catalog["products"].append(product)
            added += 1

        if not product.get("image") and info["image"]:
            dest = IMAGES_DIR / f"{product['id']}.jpg"
            try:
                download_image(f"{BASE_URL}{info['image']}", dest)
                product["image"] = f"images/{dest.name}"
            except Exception as e:
                print(f"  image failed for {product['id']}: {e}")

        store_image_rel = None
        if info["image"]:
            store_dest = IMAGES_DIR / f"{product['id']}--{STORE_SLUG}.jpg"
            try:
                download_image(f"{BASE_URL}{info['image']}", store_dest)
                store_image_rel = f"images/{store_dest.name}"
            except Exception as e:
                print(f"  store image failed for {product['id']}: {e}")

        product.setdefault("stores", [])
        store = next((s for s in product["stores"] if s["name"] == STORE_NAME), None)
        if store is None:
            store = {"name": STORE_NAME, "url": STORE_URL, "offers": []}
            product["stores"].append(store)
        offer = {"kind": "decant", "ml": info["ml"], "price": info["price"]}
        idx = next((i for i, o in enumerate(store["offers"])
                    if o["kind"] == "decant" and o["ml"] == info["ml"]), None)
        if idx is not None:
            store["offers"][idx] = track_offer(store["offers"][idx], offer)
        else:
            store["offers"].append(track_offer(None, offer))
        if store_image_rel:
            store["image"] = store_image_rel
        if info.get("product_url"):
            store["product_url"] = info["product_url"]
        synced += 1

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {added} new products, {synced} listings synced. "
          f"Nothing is ever auto-removed — run find_duplicates.py periodically.")

    status = subprocess.run(
        ["git", "status", "--porcelain", "products.json", "images/"],
        cwd=CATALOG.parent, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        print("No catalog changes to commit.")
        return

    subprocess.run(["git", "add", "products.json", "images/"], cwd=CATALOG.parent, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"sync_mo_shawky.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
