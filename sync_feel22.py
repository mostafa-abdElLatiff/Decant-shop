#!/usr/bin/env python3
"""sync_feel22.py — periodic, fully-automatic sync of eg.feel22.com into
products.json. Shopify store, standard public products.json API — same
shape as sync_darelarabia.py/sync_perfuzone.py. Only sells full bottles (no
decant/leftover options), confirmed by the user.

Covers two collections: perfume-for-him and unisex-perfume. Both are "full"
bottle listings regardless of collection — the collection only reflects
who the fragrance is marketed at, not the offer kind.

Unlike darelarabia, vendor here IS the real fragrance house (e.g. "Brut",
"Lattafa") — same situation as sync_perfuzone.py, including its ALL-CAPS
title problem, so smart_title() is reused verbatim.

Size: a product with one variant states size only in the title (e.g. "...
100ml"), parsed via a trailing-ml regex and stripped from the name. A
product with real size variants (multiple bottle sizes for the same
fragrance) exposes each one as its own priced variant with a "NNml" title
— each becomes its own "full" offer for that ml.

A sold-out variant/listing is still synced (with its price) rather than
skipped — reconcile_offers() marks it "sold" immediately instead of
dropping it, so an out-of-stock size still tells you what this store
charges and is worth waiting for a restock at.

Run manually any time with:  python3 sync_feel22.py
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
from extract import slugify, find_existing_product, unique_id_for, reconcile_offers, is_web_sourced_hero, strip_redundant_brand_suffix, CATALOG  # noqa: E402
from brand_prefixes import split_brand_prefix  # noqa: E402

STORE_NAME = "feel22"
STORE_URL = "https://eg.feel22.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
BASE_URL = "https://eg.feel22.com"
COLLECTIONS = ["perfume-for-him", "unisex-perfume"]

BRAND_ALIASES = {"rasasi": "Rasasi", "al rasasi": "Rasasi", "lattafa perfumes": "Lattafa"}

# Same rationale as sync_perfuzone.py: Title Case via .title() mangles an
# apostrophe-s ("COLLECTOR'S" -> "Collector'S") and short acronyms that
# should stay uppercase ("EDP" -> "Edp"). Handled word-by-word instead.
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


def normalize_brand(raw: str) -> str:
    raw = (raw or "").strip()
    alias = BRAND_ALIASES.get(raw.lower())
    if alias:
        return alias
    return raw.title() if raw.isupper() else raw


ML_TRAILING_RE = re.compile(r"[\s\-]*\(?\s*(\d+)\s*ml\)?\s*$", re.I)
ML_VARIANT_RE = re.compile(r"(\d+)\s*ml", re.I)
NON_PERFUME_KW = ["deodorant", "deodrant", "body spray", "candle", "diffuser", "air freshener", "gift set", "set of"]

# feel22 appends "For Men"/"For Him"/"For Her"/"For Women" to nearly every
# title as a collection tag, not as part of the actual product name — same
# generic-marketing-boilerplate situation as "Pour Homme" elsewhere in this
# catalog, and it shows up ANYWHERE in the string ("CK IN2U For Men Eau De
# Toilette", "1981 For Men Eau De Toilette"), not just at the end, so this
# strips it wherever it appears rather than only trailing. Deliberately
# leaves bare "Man"/"Woman" (no "For") alone — those are sometimes a real
# part of the official product name (e.g. a "<Line> Man" flanker), unlike
# "For Men" which no real fragrance is actually titled.
GENDER_MARKETING_RE = re.compile(r"\s*\bfor\s+(?:men|him|her|women)\b\s*", re.I)


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
            print(f"  {e.code} from eg.feel22.com, waiting {wait}s and retrying "
                  f"({attempt + 1}/{attempts})...")
            time.sleep(wait)


def fetch_collection(handle: str) -> list:
    products, page = [], 1
    while True:
        url = f"{BASE_URL}/collections/{handle}/products.json?limit=250&page={page}"
        data = json.loads(fetch_url(url))
        batch = data.get("products", [])
        if not batch:
            break
        products.extend(batch)
        page += 1
    return products


def is_non_perfume(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in NON_PERFUME_KW)


def parse_product(p: dict):
    title = (p.get("title") or "").strip()
    if not title or is_non_perfume(title):
        return None
    variants = p.get("variants") or []
    if not variants:
        return None

    # strip early so it can't strand a dangling "For Him" after the size
    # (e.g. "...100ml For Him"), which would otherwise defeat the
    # trailing-ml stripping below, and so it doesn't get in the way of the
    # brand-prefix checks either.
    title = GENDER_MARKETING_RE.sub(" ", title).strip()
    title = re.sub(r"\s+", " ", title)

    brand = normalize_brand(p.get("vendor") or "")
    name_en = title
    if brand and name_en.lower().startswith(brand.lower() + " "):
        name_en = name_en[len(brand):].strip()
    else:
        raw_vendor = (p.get("vendor") or "").strip()
        if raw_vendor and name_en.lower().startswith(raw_vendor.lower() + " "):
            name_en = name_en[len(raw_vendor):].strip()
        elif not brand:
            rest, prefix_brand = split_brand_prefix(title)
            if prefix_brand:
                brand, name_en = prefix_brand, rest

    if title.isupper():
        name_en = smart_title(name_en)

    # a single-variant listing states its size only in the title ("...
    # 100ml") — real multi-size listings carry it per-variant instead, so
    # only strip a trailing size mention here, never from a variant title.
    single_variant = len(variants) == 1
    if single_variant:
        name_en = ML_TRAILING_RE.sub("", name_en).strip()
    if brand:
        name_en = strip_redundant_brand_suffix(name_en, brand)
    if not name_en:
        return None

    offers = []
    for v in variants:
        price_str = v.get("price")
        if not price_str:
            continue
        price = round(float(price_str))
        if price <= 0:
            continue
        if single_variant:
            m = ML_TRAILING_RE.search(title) or ML_VARIANT_RE.search(title)
        else:
            m = ML_VARIANT_RE.search(v.get("title") or "")
        if not m:
            continue
        ml = int(m.group(1))
        offers.append({"kind": "full", "ml": ml, "price": price, "available": bool(v.get("available"))})
    if not offers:
        return None

    images = p.get("images") or []
    return {
        "name_en": name_en,
        "brand": brand,
        "image": images[0]["src"] if images else "",
        "product_url": f"{STORE_URL.rstrip('/')}/products/{p['handle']}" if p.get("handle") else None,
        "offers": offers,
        "shopify_id": p.get("id"),
    }


def download_image(url, dest_path):
    dest_path.write_bytes(fetch_url(url))


def main():
    seen_ids = set()
    parsed = []
    for handle in COLLECTIONS:
        print(f"Fetching collection '{handle}' ...")
        raw = fetch_collection(handle)
        print(f"  {len(raw)} listing(s)")
        for p in raw:
            if p.get("id") in seen_ids:
                continue
            info = parse_product(p)
            if not info:
                continue
            seen_ids.add(p.get("id"))
            parsed.append(info)
    print(f"{len(parsed)} qualifying listing(s) across both collections")

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
        ["git", "commit", "-m", f"sync_feel22.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
