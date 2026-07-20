#!/usr/bin/env python3
"""sync_perfuzone.py — periodic, fully-automatic sync of perfuzone-2's
"decants for him" collection into products.json. Shopify store, uses the
standard public products.json API. Only sells decants (confirmed by the
user — every listing in this collection is a small-size split, never a
full sealed bottle), so every offer is kind="decant".

Unlike emaratiscents/darelarabia, the vendor field here reliably names the
actual manufacturer (not the retailer) — but it's typed by hand and has
real spelling mistakes ("YVES SAINT LAURANT", "ESSENTIAL PEFRUMES",
"GUERLIAN", a stray "ARBIYAT PRESTIGE" missing a letter, "MAISON AL HAMBRA"
vs "MAISON ALHAMBRA" as two different spellings of one brand...) — normalize
the ones actually observed via BRAND_ALIASES rather than trust it verbatim.

Titles are ALL CAPS "<VENDOR> <PRODUCT NAME>" (vendor as a literal text
prefix, redundant with its own field) — stripped case-insensitively before
title-casing for display.

Run manually any time with:  python3 sync_perfuzone.py
"""
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
from brand_prefixes import split_brand_prefix  # noqa: E402

STORE_NAME = "perfuzone"
STORE_URL = "https://perfuzone-2.myshopify.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
COLLECTION_URL = "https://perfuzone-2.myshopify.com/collections/decants-for-him/products.json"

NON_PERFUME_KW = ["gift set", "gift box", "bundle", "travel case", "atomizer", "perfume holder"]

ML_RE = re.compile(r"^\s*(\d+)\s*ml", re.I)

# Typos/spelling variants actually observed in this store's own vendor
# field — normalized to match this catalog's established spelling for
# each brand (checked against existing products, not guessed).
BRAND_ALIASES = {
    "arbiyat prestige": "Arabiyat Prestige",
    "maison al hambra": "Maison Alhambra",
    "maison alhambra": "Maison Alhambra",
    "essential pefrumes": "Essential Parfums",
    "guerlian": "Guerlain",
    "yves saint laurant": "Yves Saint Laurent",
    "almajed oud": "Al Majed Oud",
    "dukhon al emirates": "Dkhoon Emirates",
    "dkhoon emirates": "Dkhoon Emirates",
    "viktor & rolf": "Viktor&Rolf",
    "unique'e luxury": "Unique'e Luxury",
    "matriere premiere": "Matière Première",
    "etat lire d'orange": "État Libre d'Orange",
    "riiffs": "Riffs",
    "al ezz oud": "Al-Ezz for Oud",
    "rabanne": "Paco Rabanne",
    "ahmed al mighribi": "Ahmed Al Maghribi",
}

# Title Case via .title() mangles two things Shopify's ALL-CAPS titles hit
# constantly: an apostrophe-s ("COLLECTOR'S" -> "Collector'S" instead of
# "Collector's") and short acronyms that should stay uppercase ("9PM" ->
# "9Pm", "EDP" -> "Edp"). Handled word-by-word instead of relying on .title().
KEEP_UPPER = {"pm", "am", "edp", "edt", "vip", "ysl", "jpg", "dg", "mfk", "uk", "usa"}
_WORD_RE = re.compile(r"^(\d*)([A-Za-z'.]*)$")


def smart_title(text: str) -> str:
    words = []
    for w in text.split(" "):
        m = _WORD_RE.match(w)
        if not m or not m.group(2):
            words.append(w)
            continue
        digits, letters = m.groups()
        core = letters.lower()
        words.append(digits + (letters.upper() if core in KEEP_UPPER else letters[:1].upper() + letters[1:].lower()))
    return " ".join(words)


def fetch_url(url: str, attempts: int = 5) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code not in (503, 429) or attempt == attempts - 1:
                raise
            wait = 30 * (attempt + 1)
            print(f"  {e.code} from perfuzone-2.myshopify.com, waiting {wait}s and retrying "
                  f"({attempt + 1}/{attempts})...")
            time.sleep(wait)


def fetch_all_products() -> list:
    products, page = [], 1
    while True:
        data = json.loads(fetch_url(f"{COLLECTION_URL}?limit=250&page={page}"))
        batch = data.get("products", [])
        if not batch:
            break
        products.extend(batch)
        page += 1
    return products


def normalize_brand(raw: str) -> str:
    raw = (raw or "").strip()
    alias = BRAND_ALIASES.get(raw.lower())
    if alias:
        return alias
    return raw.title() if raw.isupper() else raw


def is_non_perfume(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in NON_PERFUME_KW)


AROMATIX_LEAD_RE = re.compile(r"^x\s+aromatix\s+", re.I)


def parse_product(p: dict):
    title = (p.get("title") or "").strip()
    if not title or is_non_perfume(title):
        return None
    brand = normalize_brand(p.get("vendor") or "")

    name_en = title
    if brand and name_en.lower().startswith(brand.lower() + " "):
        name_en = name_en[len(brand):].strip()
    else:
        # brand wasn't a clean prefix (alias rewrote the text, or the title
        # uses a known abbreviation like "YSL" the vendor field spells out
        # in full) — try the raw all-caps vendor value, then a known-brand
        # abbreviation/prefix match, at the same leading position.
        raw_vendor = (p.get("vendor") or "").strip()
        if raw_vendor and name_en.lower().startswith(raw_vendor.lower() + " "):
            name_en = name_en[len(raw_vendor):].strip()
        else:
            rest, abbr_brand = split_brand_prefix(title)
            if abbr_brand:
                name_en = rest

    # "FRENCH AVENUE X AROMATIX <name>" — after stripping the "French
    # Avenue" vendor prefix above, what's left still starts with "X
    # Aromatix " (the collab marker). The rest of the catalog already
    # uses "Aromatix X French Avenue" as one brand string for this line
    # (synced from other stores) — matching it here, instead of leaving
    # "X Aromatix" stuck onto the name, is what lets this land on the
    # same already-existing products rather than creating fresh
    # "X Aromatix ..." duplicates of each one.
    if brand.lower() == "french avenue" and AROMATIX_LEAD_RE.match(name_en):
        brand = "Aromatix X French Avenue"
        name_en = AROMATIX_LEAD_RE.sub("", name_en).strip()

    # This store's own vendor tag is simply wrong for this one listing (says
    # "RABANNE" -> "Paco Rabanne", but the bottle itself is printed "RAYHAAN
    # x LEGION VALHALLA" — confirmed by hand). Not a spelling variant
    # BRAND_ALIASES can catch; a per-product override is the only fix, or
    # every sync keeps recreating it under the wrong brand.
    if name_en.strip().lower() == "valhalla":
        brand = "Rayhaan"

    if title.isupper():
        name_en = smart_title(name_en)
    if not name_en:
        return None

    offers = []
    image = None
    for v in p.get("variants") or []:
        opt = v.get("option1") or v.get("title") or ""
        m = ML_RE.match(opt)
        if not m:
            continue
        price_str = v.get("price")
        if not price_str:
            continue
        price = round(float(price_str))
        if price <= 0:
            continue
        offers.append({"kind": "decant", "ml": int(m.group(1)), "price": price,
                        "available": bool(v.get("available"))})
        if image is None and v.get("featured_image"):
            image = v["featured_image"].get("src")
    if not offers:
        return None

    if image is None:
        images = p.get("images") or []
        image = images[0]["src"] if images else ""

    return {
        "name_en": name_en,
        "brand": brand,
        "image": image or "",
        "product_url": f"{STORE_URL.rstrip('/')}/products/{p['handle']}" if p.get("handle") else None,
        "offers": offers,
    }


def download_image(url, dest_path):
    dest_path.write_bytes(fetch_url(url))


def main():
    print(f"Fetching {COLLECTION_URL} ...")
    raw = fetch_all_products()
    print(f"  {len(raw)} listing(s)")

    parsed = []
    for p in raw:
        info = parse_product(p)
        if info:
            parsed.append(info)
    print(f"{len(parsed)} listing(s) with a readable size and price")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}

    IMAGES_DIR.mkdir(exist_ok=True)
    added, synced = 0, 0

    for info in parsed:
        product = find_existing_product(catalog, info["name_en"], info["brand"])
        if product is None:
            product = {
                "id": unique_id_for(catalog, info["name_en"], info["brand"]),
                "name_ar": info["name_en"],
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

        product.setdefault("stores", [])
        store = next((s for s in product["stores"] if s["name"] == STORE_NAME), None)
        if store is None:
            store = {"name": STORE_NAME, "url": STORE_URL, "offers": []}
            product["stores"].append(store)
        store["offers"] = reconcile_offers(store["offers"], info["offers"])
        if store_image_rel:
            store["image"] = store_image_rel
        if info.get("product_url"):
            store["product_url"] = info["product_url"]
        synced += 1

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
         f"sync_perfuzone.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
