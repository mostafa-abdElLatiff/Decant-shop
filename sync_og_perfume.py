#!/usr/bin/env python3
"""sync_og_perfume.py — periodic, fully-automatic sync of og-perfume.com's
"decants" collection into products.json. Shopify store, uses the standard
public products.json API.

Confirmed messy by the user, and it shows:
  - This ONE collection mixes decants, full bottles, AND leftover ("as-shown")
    bottles in the same listing's variants — never separated into different
    collections like every other store. Kind/size come from the variant
    TITLE text, not the collection: "**Decant Nml**" -> decant, "Full Size
    Nml" -> full, and a family of Arabic "كمية بالزجاجة Nمل" / English "N ml
    in bottle" phrasings (looked up across many spelling variants actually
    seen: كميه/كمية, بالزجاجة/بالزجاجه, with/without spaces, Arabic-Indic
    digits) -> leftover, since that phrase literally means "the amount
    that's in the bottle" — i.e. whatever's left in an opened one. A variant
    matching none of these (accessories like "Full Box", "Perfume Holder")
    has no readable size and is skipped, same as every other store.
  - vendor is USUALLY the real manufacturer, but not always — one listing
    titled "Vanilla Voyage Maison Asrar" (Maison Asrar spelled right there
    in the title) had vendor "Gulf Orchid", plainly wrong. So: try to find
    a KNOWN brand as a prefix or suffix of the title first (title-embedded
    mentions were correct every time this was checked); only fall back to
    the vendor field when the title has no recognizable brand text.

Run manually any time with:  python3 sync_og_perfume.py
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
from brand_prefixes import split_brand_prefix, split_brand_suffix  # noqa: E402

STORE_NAME = "og-perfume"
STORE_URL = "https://og-perfume.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
COLLECTION_URL = "https://og-perfume.com/collections/decants-%D8%A7%D9%84%D8%AA%D9%82%D8%B3%D9%8A%D9%85%D8%A7%D8%AA/products.json"

NON_PERFUME_KW = ["gift set", "gift box", "bundle", "travel case", "perfume holder", "atomizer"]

ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
DECANT_RE = re.compile(r"decant\s*(\d+)\s*ml", re.I)
FULL_RE = re.compile(r"full\s*size\s*(\d+)\s*ml", re.I)
# "كمية/كميه بالزجاجة/بالزجاجه <N> مل" or "<N> ml in bottle" — literally
# "the amount that's in the bottle", i.e. an opened/partial bottle.
LEFTOVER_MARK_RE = re.compile(r"كمي|in\s*bottle", re.I)
ANY_NUM_RE = re.compile(r"(\d+)")
# a size baked into the product TITLE itself (not the variant) — stripped
# before brand detection so e.g. "Nude Coral Diamond 150ml" doesn't leave
# "150ml" stuck onto the display name.
TITLE_SIZE_RE = re.compile(r"\s*\d+\s*ml\s*$", re.I)

BRAND_ALIASES = {
    "dkhoon emirates": "Dkhoon Emirates", "ibrahim al qurashi": "Ibrahim Al Qurashi",
    "ibrahim al  qurashi": "Ibrahim Al Qurashi", "riiffs": "Riffs",
    "maison al hambra": "Maison Alhambra",
}


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
            print(f"  {e.code} from og-perfume.com, waiting {wait}s and retrying "
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
    return BRAND_ALIASES.get(raw.lower(), raw)


def parse_variant_kind_ml(title: str):
    t = (title or "").translate(ARABIC_DIGITS)
    m = DECANT_RE.search(t)
    if m:
        return "decant", int(m.group(1))
    m = FULL_RE.search(t)
    if m:
        return "full", int(m.group(1))
    if LEFTOVER_MARK_RE.search(t):
        m = ANY_NUM_RE.search(t)
        if m:
            return "leftover", int(m.group(1))
    return None, None


def is_non_perfume(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in NON_PERFUME_KW)


def _fixup(rest: str, brand: str):
    # "Aromatix" alone (matched via BRAND_PREFIXES, which only lists the
    # bare word) always means this catalog's "Aromatix X French Avenue"
    # collab line — every other store's already-synced products for this
    # line use that full brand string, so leaving it as bare "Aromatix"
    # would silently create a fresh duplicate of each one instead of
    # landing on what's already there.
    if brand.strip().lower() == "aromatix":
        return rest, "Aromatix X French Avenue"
    return rest, brand


def extract_name_and_brand(title: str, vendor: str):
    """Prefer a brand name found embedded in the title itself (prefix or
    suffix) over the vendor field — the title was right every time this
    got checked by hand, the vendor field wasn't always."""
    stripped_title = TITLE_SIZE_RE.sub("", title).strip()

    rest, brand = split_brand_suffix(stripped_title)
    if brand:
        return _fixup(rest, brand)
    rest, brand = split_brand_prefix(stripped_title)
    if brand:
        return _fixup(rest, brand)
    return stripped_title, normalize_brand(vendor)


def parse_product(p: dict):
    title = (p.get("title") or "").strip()
    if not title or is_non_perfume(title):
        return None
    name_en, brand = extract_name_and_brand(title, p.get("vendor") or "")
    if not name_en:
        return None

    offers = []
    image = None
    for v in p.get("variants") or []:
        opt = v.get("option1") or v.get("title") or ""
        kind, ml = parse_variant_kind_ml(opt)
        if not kind:
            continue
        price_str = v.get("price")
        if not price_str:
            continue
        price = round(float(price_str))
        if price <= 0:
            continue
        offers.append({"kind": kind, "ml": ml, "price": price, "available": bool(v.get("available"))})
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
         f"sync_og_perfume.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
