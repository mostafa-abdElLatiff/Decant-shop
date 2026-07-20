#!/usr/bin/env python3
"""sync_emaratiscents.py — periodic, fully-automatic sync of
emaratiscents.com's men's collection into products.json. Shopify store,
uses the standard public products.json API. Only sells full bottles (no
decant/leftover options), confirmed by the user.

Brand and size aren't in a single structured field — body_html mixes two
different description templates across products, so both are parsed with
a couple of fallback patterns:
  - brand: a "By <Brand>" line, or "<Name> by <Brand> is a ..." prose, or
    (Lattafa only) a lattafa.com/barcode/ link in the body with no other
    brand text — about half the catalog doesn't state a brand anywhere
    findable, left blank rather than guessed.
  - size: "<n> ML" in the title, else "SIZE : <n> ML" in the body, else
    any "<n> ML" mention in the body; skipped (not synced) if none found,
    same as every other store's "don't guess a size" rule.

A listing with no price is skipped (nothing to show), but a sold-out one
WITH a price is still synced and marked "sold" right away — an
out-of-stock price is still useful, it's what to watch for a restock at.

Run manually any time with:  python3 sync_emaratiscents.py
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

STORE_NAME = "emaratiscents"
STORE_URL = "https://emaratiscents.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
COLLECTION_URL = "https://emaratiscents.com/collections/men/products.json"

NON_PERFUME_KW = [
    "deodrant", "deodorant", "hair serum", "musk oil", "oudi oil",
    "oil box", "scented soap", "candle", "diffuser", "air freshener",
    "incense stick",
]

# "by" alone is far too common in ordinary description prose ("inspired
# BY the energy...", "crafted BY a Gen Z perfumer...") to search for
# anywhere in the text — only trust it in two specific, anchored shapes:
# a standalone "By <Brand>" sentence (nothing else in it), or "<Brand>"
# immediately following the product's own title text ("Khamrah Waha BY
# Lattafa is..."), never a generic mid-paragraph mention.
STANDALONE_BY_RE = re.compile(r"(?:^|\.\s+)By\s+([A-Z][A-Za-z&.' ]{2,25}?)\s*(?:\.|$)")
BRAND_STOPWORDS = {
    "the", "a", "an", "and", "for", "with", "both", "of", "is", "as",
    "description", "men", "women", "unisex",
}
TITLE_ML_RE = re.compile(r"(\d{2,4})\s*ML\b", re.I)
BODY_SIZE_RE = re.compile(r"SIZE\s*:\s*(\d{2,4})\s*ML", re.I)


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
            print(f"  {e.code} from emaratiscents.com, waiting {wait}s and retrying "
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


def strip_html(html: str) -> str:
    # turn paragraph/line breaks into a sentence boundary BEFORE collapsing
    # tags to spaces, so e.g. "By Lattafa</p><p>Khamrah Waha is..." doesn't
    # read as one run-on sentence "by Lattafa Khamrah Waha is..." that
    # swallows the next paragraph's product-name mention into the brand
    # regex match.
    text = re.sub(r"</p>|<br\s*/?>|</div>", ". ", html or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


# the site's own copy sometimes spells a brand differently than this
# catalog's already-established convention (e.g. "Al Rasasi" here vs
# "Rasasi" on every other store) — reconcile the couple of known ones
# rather than let a new spelling variant slip in.
BRAND_ALIASES = {"rasasi": "Rasasi", "al rasasi": "Rasasi", "ibraq": "Ibraq", "lattafa perfumes": "Lattafa"}

# extract_brand() reads free-text description prose (no structured vendor
# field on this store), which occasionally latches onto the wrong brand
# entirely — a stray "by <other brand>" comparison in the copy, or a
# boilerplate barcode-checker link reused across listings regardless of
# actual brand. Caught by hand (confirmed via the product's own bottle
# photo); a per-product override since it's a wrong-text problem, not a
# spelling variant BRAND_ALIASES could catch.
PRODUCT_BRAND_OVERRIDES = {
    "kahilan": "Dkhoon Emirates",
    "tiramisu coco": "Zimaya",
}


def _is_plausible_brand(candidate: str) -> bool:
    words = candidate.split()
    if not words or len(words) > 4:
        return False
    return not any(w.lower() in BRAND_STOPWORDS for w in words)


def extract_brand(title: str, body_html: str) -> str:
    text = strip_html(body_html)
    brand = ""

    m = STANDALONE_BY_RE.search(text)
    if m and _is_plausible_brand(m.group(1)):
        brand = m.group(1).strip()

    if not brand and title:
        # "<Title> by <Brand> is/,." — anchored to the product's own
        # title so it can't latch onto an unrelated "by" elsewhere in the
        # description prose.
        anchored_re = re.compile(re.escape(title) + r"\s+by\s+([A-Z][A-Za-z&.' ]{2,25}?)(?:\s+is\b|[.,]|$)", re.I)
        m = anchored_re.search(text)
        if m and _is_plausible_brand(m.group(1)):
            brand = m.group(1).strip()

    if not brand and "lattafa.com/barcode" in (body_html or ""):
        brand = "Lattafa"

    return BRAND_ALIASES.get(brand.lower(), brand)


def extract_ml(title: str, body_html: str):
    m = TITLE_ML_RE.search(title)
    if m:
        return int(m.group(1))
    text = strip_html(body_html)
    m = BODY_SIZE_RE.search(text)
    if m:
        return int(m.group(1))
    m = TITLE_ML_RE.search(text)
    if m:
        return int(m.group(1))
    return None


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
    # sold out still gets synced (with its price) rather than skipped —
    # reconcile_offers() marks it "sold" immediately instead of dropping it,
    # so an out-of-stock listing still tells you what this store charges
    # and is worth waiting for a restock at, instead of vanishing outright.
    available = bool(variants[0].get("available"))
    price_str = variants[0].get("price")
    if not price_str:
        return None
    price = round(float(price_str))
    if price <= 0:
        return None

    body_html = p.get("body_html") or ""
    ml = extract_ml(title, body_html)
    if not ml:
        return None

    brand = extract_brand(title, body_html)
    # title itself is ALL CAPS store-wide convention — normalize to title
    # case for display, then let strip_redundant_brand_suffix drop the
    # brand if it's redundantly baked onto the end (matches this
    # catalog's existing naming convention for every other store).
    name_en = title.title()
    name_en = re.sub(rf"\b{re.escape(str(ml))}\s*ML\b", "", name_en, flags=re.I).strip()
    if brand:
        # this store's own titles restate the brand as a literal "... By
        # <Brand>" suffix even when already declared via extract_brand()
        # ("Al Fareed By Arabian Oud", brand "Arabian Oud") — left in,
        # that extra "by" token beats find_existing_product's matching
        # against the already-split sibling ("Al Fareed") and silently
        # duplicates it on every re-sync. strip_redundant_brand_suffix()
        # alone won't touch this (it deliberately preserves a "By <Brand>"
        # suffix — could be a real designer collab name), but on this
        # store's own title convention "By X" always just means
        # attribution, so strip it outright first.
        #
        # A plain f"by {brand}" string match misses it when the raw title
        # hyphenates the brand differently than the canonical spelling
        # does ("Tuwaiq By Al-Mas" vs brand "Almas") — bit us for real,
        # this exact product sat undetected as a duplicate for a while.
        # Letting whitespace/hyphens vary between each letter of the
        # brand (only ever matched right after "by", so it can't misfire
        # on an unrelated word) catches that without needing every
        # hyphenation variant spelled out by hand.
        brand_flex = r"[\s-]*".join(re.escape(ch) for ch in brand)
        by_brand_re = re.compile(r"\bby[\s-]*" + brand_flex + r"\s*$", re.I)
        m = by_brand_re.search(name_en)
        if m:
            name_en = name_en[: m.start()].rstrip(" -—–|,").strip()
        name_en = strip_redundant_brand_suffix(name_en, brand)

    override = PRODUCT_BRAND_OVERRIDES.get(name_en.strip().lower())
    if override:
        brand = override

    images = p.get("images") or []
    return {
        "name_en": name_en,
        "brand": brand,
        "image": images[0]["src"] if images else "",
        "product_url": f"{STORE_URL.rstrip('/')}/products/{p['handle']}" if p.get("handle") else None,
        "offer": {"kind": "full", "ml": ml, "price": price, "available": available},
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

    # Each fragrance can appear as more than one `info` entry (different
    # categories/sizes) — collect everything seen this run per product
    # first, then reconcile once at the end, so a size that's genuinely
    # gone gets marked sold instead of just sitting there stale forever.
    touched = {}  # product id -> {"product": dict, "offers": [...], "store_image": str|None, "product_url": str|None}

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
         f"sync_emaratiscents.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
