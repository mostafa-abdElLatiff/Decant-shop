#!/usr/bin/env python3
"""sync_eldesoki.py — periodic, fully-automatic sync of
eldesoki-fragrances.com into products.json. WordPress/WooCommerce store —
uses the public WooCommerce Store API (no key needed) rather than scraping
HTML. Unlike roseperfume (one Shopify product with multiple size variants),
this store lists every individual size as its own separate "product", split
across three category IDs the user identified by URL:
  24 = full bottles, 27 = decants (fixed-size testers, not 3/5/10ml
       selections like other stores), 28 = leftover decant bottles.
Each listing's title is "English name<newline>Arabic name", with the size
embedded in the English line (e.g. "Strike Black Assaf 125ML") — parsed
from there rather than trusted from the category label, since actual sizes
vary within a category.

Run manually any time with:  python3 sync_eldesoki.py
"""
import html
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import slugify, find_existing_product, unique_id_for, reconcile_offers, is_web_sourced_hero, CATALOG  # noqa: E402

STORE_NAME = "eldesoki-fragrances"
STORE_URL = "https://eldesoki-fragrances.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
API_BASE = "https://eldesoki-fragrances.com/wp-json/wc/store/v1/products"

CATEGORY_KIND = {24: "full", 27: "decant", 28: "leftover"}

# Best-effort Arabic-brand-suffix -> Latin brand name lookup, built from
# sampling the "... من <brand>" suffix actually used across ~780 listings.
# Deliberately NOT exhaustive — rarer/ambiguous suffixes (e.g. "عطوري",
# "لابونير", "اثينا") are left unmapped so the product gets brand="" rather
# than a guessed brand, same "don't guess" policy used elsewhere.
BRAND_MAP = {
    "فرينش افينو": "French Avenue", "فرينش أڤينو": "French Avenue",
    "باريس كورنر": "Paris Corner",
    "ابراق": "Ibraq",
    "فراجرانس وورلد": "Fragrance World", "فراجرنس وورلد": "Fragrance World",
    "عساف": "Assaf",
    "ارماف": "Armaf", "اراماف": "Armaf",
    "عربيات بريستيچ": "Arabiyat Prestige",
    "خادلاچ": "Khadlaj",
    "لطافة": "Lattafa",
    "سويس اريبيان": "Swiss Arabian",
    "الرصاصي": "Rasasi",
    "الهامبرا": "Alhambra", "ميزون الهامبرا": "Maison Alhambra",
    "زيمايا": "Zimaya", "زمايا": "Zimaya",
    "افنان": "Afnan", "أفنان": "Afnan",
    "لو فالكون": "Le Falconé Perfumes",
    "وادي الخليج": "Wadi Al Khaleej",
    "ايف سان لوران": "Yves Saint Laurent",
    "ناسوماتو": "Nasomatto",
    "ابراهيم القرشي": "Ibrahim Al Qurashi", "القرشي": "Ibrahim Al Qurashi",
    "فرانك اوليفير": "Franck Olivier",
    "الرحاب": "Al Rehab",
    "الماس": "Almas",
}

ML_RE = re.compile(r"(\d+)\s*ML", re.I)
BRAND_SUFFIX_RE = re.compile(r"من\s+(.+?)\s*$")
STRIP_ML_JUNK_RE = re.compile(r"[()]|[٠-٩\d]+\s*مل[يى]?")
ARABIC_RE = re.compile(r"[؀-ۿ]")
# This store lists the same fragrance separately per size/category, and
# tags the small-size listing "Tester" and the full-bottle listing "FA"
# (French Avenue abbreviation) — neither is part of the actual fragrance
# name, so both need stripping before name-matching against a listing for
# the same fragrance in another category (otherwise "Amber Empire tester"
# and "Amber Empire FA" each look like a different, brand-new product
# instead of two more sizes of the existing "Amber Empire").
TRAILING_TAG_RE = re.compile(r"\s+(FA|Tester)\s*$", re.I)


def fetch_url(url: str, attempts: int = 5) -> bytes:
    """Same transient-503 retry pattern as sniffz/roseperfume."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in (503, 429) or attempt == attempts - 1:
                raise
            wait = 30 * (attempt + 1)
            print(f"  {e.code} from eldesoki-fragrances.com, waiting {wait}s and retrying "
                  f"({attempt + 1}/{attempts})...")
            time.sleep(wait)


def fetch_category(cat_id: int) -> list:
    products, page = [], 1
    while True:
        data = json.loads(fetch_url(f"{API_BASE}?category={cat_id}&per_page=100&page={page}"))
        if not data:
            break
        products.extend(data)
        page += 1
    return products


def clean_brand_suffix(raw: str) -> str:
    return STRIP_ML_JUNK_RE.sub("", raw).strip()


def parse_product(p: dict, kind: str):
    """Return a normalized dict, or None if unavailable / size unreadable."""
    if not p.get("is_in_stock", True) or not p.get("is_purchasable", True):
        return None
    raw_name = html.unescape((p.get("name") or "").strip())
    lines = raw_name.split("\n")
    if len(lines) > 1:
        name_en, name_ar = lines[0].strip(), lines[1].strip()
    else:
        # a handful of listings run English and Arabic together on one line
        # with no newline separator at all — split at the first Arabic
        # character instead of assuming the "\n"-delimited layout.
        m = ARABIC_RE.search(raw_name)
        name_en = raw_name[:m.start()].strip() if m else raw_name
        name_ar = raw_name[m.start():].strip() if m else raw_name
    if not name_en:
        return None

    ml_matches = list(ML_RE.finditer(name_en))
    if not ml_matches:
        return None
    last = ml_matches[-1]
    ml = int(last.group(1))
    # strip the matched size (wherever it falls — start, middle, or end) out
    # of the display name, e.g. "Mexican Tobacco (20ml)" -> "Mexican
    # Tobacco", "External Club 200ML MPF" -> "External Club MPF" — otherwise
    # the size stays baked into name_en and breaks matching against this
    # same fragrance already in the catalog under its plain name.
    name_en = name_en[:last.start()] + name_en[last.end():]
    name_en = re.sub(r"[()]", "", name_en)
    name_en = re.sub(r"\s+", " ", name_en).strip()
    if not name_en:
        return None

    tag_brand = ""
    tm = TRAILING_TAG_RE.search(name_en)
    if tm:
        if tm.group(1).upper() == "FA":
            tag_brand = "French Avenue"
        name_en = name_en[:tm.start()].strip()
        if not name_en:
            return None

    price_minor = (p.get("prices") or {}).get("price")
    if not price_minor:
        return None
    minor_unit = (p.get("prices") or {}).get("currency_minor_unit", 2)
    price = round(int(price_minor) / (10 ** minor_unit))
    if price <= 0:
        return None

    brand = tag_brand
    if not brand:
        bm = BRAND_SUFFIX_RE.search(name_ar)
        if bm:
            brand = BRAND_MAP.get(clean_brand_suffix(bm.group(1)), "")

    images = p.get("images") or []
    return {
        "name_en": name_en,
        "name_ar": name_ar,
        "brand": brand,
        "image": images[0]["src"] if images else "",
        "product_url": p.get("permalink"),
        "offer": {"kind": kind, "ml": ml, "price": price},
    }


def download_image(url, dest_path):
    dest_path.write_bytes(fetch_url(url))


def main():
    parsed = []
    for cat_id, kind in CATEGORY_KIND.items():
        print(f"Fetching category {cat_id} ({kind}) ...")
        raw = fetch_category(cat_id)
        print(f"  {len(raw)} listing(s)")
        for p in raw:
            info = parse_product(p, kind)
            if info:
                parsed.append(info)
    print(f"{len(parsed)} in-stock listing(s) with a readable size")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}

    IMAGES_DIR.mkdir(exist_ok=True)
    added, synced = 0, 0

    # This store lists every size as its own separate listing, so a
    # fragrance can show up as several `info` entries — collect everything
    # seen this run per product first, then reconcile once at the end
    # (rather than upsert-only), so a size that's genuinely gone gets
    # marked sold instead of just sitting there stale forever.
    touched = {}  # product id -> {"product": dict, "offers": [...], "store_image": str|None, "product_url": str|None}

    for info in parsed:
        product = find_existing_product(catalog, info["name_en"], info["brand"])
        if product is None:
            product = {
                "id": unique_id_for(catalog, info["name_en"], info["brand"]),
                "name_ar": info["name_ar"],
                "name_en": info["name_en"],
                "brand": info["brand"],
                "dupe_of": [],
                "image": "",
                "accords": [],
                "stores": [],
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
        entry["offers"].append(info["offer"])
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
        ["git", "commit", "-m",
         f"sync_eldesoki.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
