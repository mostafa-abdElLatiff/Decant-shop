#!/usr/bin/env python3
"""
sync_faces.py — sync faces.eg's men's-perfume catalog into products.json.
No AI/vision: this is server-rendered Salesforce Commerce Cloud (SFCC)
HTML — every product tile on the category grid carries a
`data-gtm-enhancedecommerce-impression` JSON attribute (name, brand,
price, size, in-stock) meant for Google Analytics, which turns out to be
a clean structured-data source for scraping too.

Two-step crawl, same shape as sync_mo_shawky.py's sibling-size crawl:
1. Walk the category grid (`/en/perfume-for-men`, then SFCC's own
   `Search-UpdateGrid` AJAX endpoint for `start=48,96,...` pages) to get
   one tile per product — but the grid only ever shows ONE size/price per
   product (whichever variant is selected by default), even for products
   sold in several sizes.
2. Visit each product's own detail page, where every size IS rendered
   (a row of "Xml" swatch buttons, each with its own price) — this is
   the only place the full size/price list actually exists. Run with
   bounded concurrency (DETAIL_CRAWL_WORKERS at a time), not serially —
   this store has ~470 products in this one category alone.

The grid's AJAX endpoint 500s without a same-origin Referer header (and
without carrying forward the session cookie the first page load sets) —
both handled by a shared urllib opener with a cookie jar.

Availability: no confirmed "out of stock" example was found on a size
button while building this (every button size-tested was purchasable),
so every parsed size defaults to available=True — same "don't invent a
sold-out state you haven't actually seen" stance sync_mo_shawky.py takes
for its own store. Revisit if a real sold-out variant ever turns up.

Run whenever you want to refresh this store's listings:

    python sync_faces.py

Commits locally if anything changed — never pushes. Review with
`git log` / `git diff` and push yourself when ready.
"""
import concurrent.futures
import html
import json
import re
import subprocess
import sys
import time
import urllib.request
from http.cookiejar import CookieJar
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import slugify, find_by_store_url, find_existing_product, unique_id_for, reconcile_offers, is_web_sourced_hero, canonicalize_new_identity, brand_category, CATALOG  # noqa: E402

BASE_URL = "https://www.faces.eg"
CATEGORY_PATH = "/en/perfume-for-men"
CATEGORY_ID = "perfume-for-men"
GRID_PATH = "/on/demandware.store/Sites-Faces_EG-Site/en_EG/Search-UpdateGrid"
STORE_NAME = "faces"
STORE_URL = f"{BASE_URL}{CATEGORY_PATH}"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
PAGE_SIZE = 48
DETAIL_CRAWL_WORKERS = 8

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
# session cookie from the first request must be replayed on every later
# request (grid pagination, product pages) or the grid endpoint 500s
_opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))


def fetch(url: str, referer: str = None, ajax: bool = False, attempts: int = 4) -> str:
    headers = {"User-Agent": _UA}
    if referer:
        headers["Referer"] = referer
    if ajax:
        # the Search-UpdateGrid endpoint 500s without this -- Referer
        # alone isn't enough, confirmed by hand before writing this
        headers["X-Requested-With"] = "XMLHttpRequest"
    req = urllib.request.Request(url, headers=headers)
    for attempt in range(attempts):
        try:
            with _opener.open(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="ignore")
        except Exception as e:
            if attempt == attempts - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"  fetch failed for {url} ({e}), retrying in {wait}s ({attempt + 1}/{attempts})...")
            time.sleep(wait)


def download_image(url: str, dest_path: Path, attempts: int = 4):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                dest_path.write_bytes(resp.read())
            return
        except Exception as e:
            if attempt == attempts - 1:
                raise
            time.sleep(5 * (attempt + 1))


TILE_RE = re.compile(r'data-pid="(\d+)"')
IMPRESSION_RE = re.compile(r'data-gtm-enhancedecommerce-impression="([^"]*)"')
HREF_RE = re.compile(r'href="(/en/p/[^"]+\.html)"')
IMG_RE = re.compile(r'<img\s+class="picture-img[^"]*"\s+srcset="([^"?]+)')
SIZE_ML_RE = re.compile(r"(\d+)\s*ml", re.I)


def parse_ml(size_text):
    if not size_text:
        return None
    m = SIZE_ML_RE.search(size_text)
    return int(m.group(1)) if m else None


def parse_tiles(page_html: str) -> list:
    """Split into per-tile chunks anchored on data-pid, then pull each
    field out of its own chunk independently -- more robust than
    assuming one fixed offset between fields, since the two page shapes
    this hits (the full category page vs. a Search-UpdateGrid AJAX
    fragment) don't render byte-identical markup around a tile."""
    tiles = []
    matches = list(TILE_RE.finditer(page_html))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(page_html), start + 6000)
        chunk = page_html[start:end]
        imp_m = IMPRESSION_RE.search(chunk)
        if not imp_m:
            continue
        try:
            items = json.loads(html.unescape(imp_m.group(1)))
        except json.JSONDecodeError:
            continue
        if not items:
            continue
        item = items[0]
        href_m = HREF_RE.search(chunk)
        img_m = IMG_RE.search(chunk)
        tiles.append({
            "item_id": item.get("item_id"),
            "name": item.get("item_name") or "",
            "brand": item.get("item_brand") or "",
            "price": item.get("price"),
            "size": item.get("item_size"),
            "in_stock": item.get("item_in_stock", True),
            "url": f"{BASE_URL}{href_m.group(1)}" if href_m else None,
            "image": img_m.group(1) if img_m else "",
        })
    return tiles


def fetch_category_tiles() -> list:
    referer = f"{BASE_URL}{CATEGORY_PATH}"
    first_html = fetch(referer)
    total_m = re.search(r'class="total[^"]*">\s*(\d+)\s*items', first_html)
    total = int(total_m.group(1)) if total_m else None

    tiles = parse_tiles(first_html)
    seen_ids = {t["item_id"] for t in tiles}
    start = PAGE_SIZE
    while total is None or len(seen_ids) < total:
        grid_html = fetch(f"{BASE_URL}{GRID_PATH}?cgid={CATEGORY_ID}&start={start}&sz={PAGE_SIZE}", referer=referer, ajax=True)
        page_tiles = parse_tiles(grid_html)
        new = [t for t in page_tiles if t["item_id"] not in seen_ids]
        if not new:
            break
        tiles.extend(new)
        seen_ids.update(t["item_id"] for t in new)
        start += PAGE_SIZE
    return tiles


# Each size swatch button on a product's own detail page carries the exact
# ml + price for that variant (the category grid only ever shows one).
# Captures the button's class list too, so an "unselectable"/"disabled"
# class (if this store ever renders one for a sold-out size) can flag it
# -- see the availability note in the module docstring.
SIZE_BUTTON_RE = re.compile(
    r'<button\s+class="([^"]*)"[^>]*data-attr-type="size"[^>]*data-attr-value="(\d+)ml"[^>]*data-pid="(\d+)"[^>]*>(.*?)</button>',
    re.S,
)


# This store's own product-name text bakes the size into the name itself
# (e.g. "9pm Elixir EDP 100 ML") -- redundant with the offer's own `ml`
# field, and it silently defeated cross-store duplicate matching (a plain
# "9pm Elixir" from another store never matched this store's "...100 ML"
# text). Strip only the size+unit; concentration words (EDP/EDT/Tester/
# etc.) are left alone since those ARE meaningful, real distinguishing
# information this catalog already tracks as separate products elsewhere.
_SIZE_UNIT_RE = re.compile(r"[\s\-]*\b\d+\s?(?:ml|gr|oz)\b", re.I)


def clean_name(name: str) -> str:
    cleaned = _SIZE_UNIT_RE.sub("", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -+")
    words = cleaned.split(" ")
    deduped = []
    i = 0
    while i < len(words):
        if i + 3 < len(words) and words[i].lower() == words[i + 2].lower() and words[i + 1].lower() == words[i + 3].lower():
            deduped.extend(words[i:i + 2])
            i += 4
        else:
            deduped.append(words[i])
            i += 1
    return " ".join(deduped).strip()


def fetch_detail_sizes(url: str, referer: str) -> list:
    page_html = fetch(url, referer=referer)
    sizes = []
    for cls, ml, pid, body in SIZE_BUTTON_RE.findall(page_html):
        price_m = re.search(r"select-attribute-price[^>]*>[^\d]*([\d,]+)", html.unescape(body))
        if not price_m:
            continue
        available = "unselectable" not in cls and "disabled" not in cls
        sizes.append({"ml": int(ml), "price": int(price_m.group(1).replace(",", "")), "sku": pid, "available": available})
    return sizes


def main():
    print(f"Fetching {BASE_URL}{CATEGORY_PATH} ...")
    tiles = fetch_category_tiles()
    print(f"  {len(tiles)} listing(s)")

    referer = f"{BASE_URL}{CATEGORY_PATH}"
    urls = [t["url"] for t in tiles if t.get("url")]
    print(f"  checking each listing's detail page for its full size list ({DETAIL_CRAWL_WORKERS} at a time)...")
    sizes_by_url = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=DETAIL_CRAWL_WORKERS) as pool:
        futures = {pool.submit(fetch_detail_sizes, u, referer): u for u in urls}
        for fut in concurrent.futures.as_completed(futures):
            u = futures[fut]
            try:
                sizes_by_url[u] = fut.result()
            except Exception as e:
                print(f"  ✗ couldn't fetch {u}: {e}")

    parsed = []
    for t in tiles:
        name_en = clean_name(re.sub(r"\s+", " ", html.unescape(t["name"])).strip())
        brand = html.unescape(t["brand"]).strip()
        if not name_en:
            continue
        sizes = sizes_by_url.get(t.get("url")) or []
        if not sizes:
            # single-variant product with no size-swatch row on its detail
            # page -- fall back to the grid tile's own price/size (only
            # usable when the store actually populated item_size there;
            # otherwise skip rather than guess a volume)
            ml = parse_ml(t.get("size"))
            if ml and t.get("price"):
                sizes = [{"ml": ml, "price": int(t["price"]), "available": t.get("in_stock", True)}]
        if not sizes:
            print(f"  skip (no size/price found): {name_en!r}")
            continue
        for sz in sizes:
            parsed.append({
                "name_en": name_en, "brand": brand,
                "ml": sz["ml"], "price": sz["price"], "available": sz.get("available", True),
                "image": t.get("image", ""), "product_url": t.get("url"),
            })
    print(f"  {len(parsed)} offer(s) across {len(tiles)} product(s)")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}
    IMAGES_DIR.mkdir(exist_ok=True)
    added, synced = 0, 0

    # Each product can have several `info` entries (one per size) --
    # collect everything seen this run per product first, then reconcile
    # once at the end, so a size that's genuinely gone gets marked sold
    # instead of just sitting there stale forever.
    touched = {}  # product id -> {"product": dict, "offers": [...], "store_image": str|None, "product_url": str|None}

    for info in parsed:
        product = find_by_store_url(catalog, STORE_NAME, info.get("product_url")) \
            or find_existing_product(catalog, info["name_en"], info["brand"])
        if product is None:
            name_en, brand = canonicalize_new_identity(info["name_en"], info["brand"])
            product = {
                "id": unique_id_for(catalog, name_en, brand),
                "name_ar": "", "name_en": name_en, "brand": brand, "category": brand_category(brand),
                "dupe_of": [], "image": "", "accords": [], "stores": [],
            }
            catalog["products"].append(product)
            added += 1

        if not is_web_sourced_hero(product) and info["image"]:
            dest = IMAGES_DIR / f"{product['id']}.jpg"
            try:
                download_image(info["image"], dest)
                product["image"] = f"images/{dest.name}"
                product["_hero_source"] = STORE_NAME
            except Exception as e:
                print(f"  image failed for {product['id']}: {e}")

        store_image_rel = None
        if info["image"]:
            store_dest = IMAGES_DIR / f"{product['id']}--{STORE_SLUG}.jpg"
            try:
                download_image(info["image"], store_dest)
                store_image_rel = f"images/{store_dest.name}"
            except Exception as e:
                print(f"  store image failed for {product['id']}: {e}")

        entry = touched.setdefault(product["id"], {"product": product, "offers": [], "store_image": None, "product_url": None})
        entry["offers"].append({"kind": "full", "ml": info["ml"], "price": info["price"], "available": info["available"]})
        if store_image_rel:
            entry["store_image"] = store_image_rel
        if info.get("product_url"):
            entry["product_url"] = info["product_url"]
        synced += 1

    for entry in touched.values():
        product = entry["product"]
        product.setdefault("stores", [])
        store = next((s for s in product["stores"] if s["name"] == STORE_NAME), None)
        if store is None:
            store = {"name": STORE_NAME, "url": STORE_URL, "offers": []}
            product["stores"].append(store)
        store["offers"] = reconcile_offers(store["offers"], entry["offers"])
        if entry["store_image"]:
            store["image"] = entry["store_image"]
        if entry["product_url"]:
            store["product_url"] = entry["product_url"]

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {added} new products, {synced} listing(s) synced. "
          f"Nothing is ever auto-removed — run find_duplicates.py periodically to "
          f"catch near-duplicates, and review stale listings by hand.")

    status = subprocess.run(
        ["git", "status", "--porcelain", "products.json", "images/"],
        cwd=CATALOG.parent, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        print("No catalog changes to commit.")
        return

    subprocess.run(["git", "add", "products.json", "images/"], cwd=CATALOG.parent, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"sync_faces.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
