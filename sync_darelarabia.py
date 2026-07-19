#!/usr/bin/env python3
"""sync_darelarabia.py — periodic, fully-automatic sync of darelarabia.com's
men's collection into products.json. Shopify store, uses the standard
public products.json API — same shape as sync_emaratiscents.py. Only sells
full bottles (no decant/leftover options), confirmed by the user.

Brand and size aren't in a single structured field:
  - vendor is always the retailer's own name in inconsistent casing ("Dar
    El Arabia" / "dar-al-arabia"), never the actual fragrance house — same
    situation as emaratiscents, so it's ignored entirely.
  - brand: body_html almost always opens with "<Title> by <Brand>" (often
    inside a <strong> tag, sometimes preceded by "Discover ") — parsed with
    a title-anchored pattern, same approach as sync_emaratiscents.py's
    extract_brand(). Left blank (not guessed) when absent.
  - size: unlike emaratiscents (regex over the title text), this store puts
    it directly in the variant's own option ("100ML", "125ML", "80ML",
    sometimes "150 ML" with a space) — parsed straight from there. A
    "Default Title" variant means the store genuinely never states a size
    anywhere; skipped rather than guessed, same as every other store.

A listing with no price is skipped (nothing to show), but a sold-out one
WITH a price is still synced and marked "sold" right away — an
out-of-stock price is still useful, it's what to watch for a restock at.

Run manually any time with:  python3 sync_darelarabia.py
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

STORE_NAME = "dar.elarabia"
STORE_URL = "https://darelarabia.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
COLLECTION_URL = "https://darelarabia.com/collections/men/products.json"

NON_PERFUME_KW = [
    "deodrant", "deodorant", "hair serum", "musk oil", "oudi oil",
    "oil box", "scented soap", "candle", "diffuser", "air freshener",
    "incense stick", "body spray",
]

# Same anchoring rationale as sync_emaratiscents.py's STANDALONE_BY_RE: "by"
# alone is too common in ordinary description prose to search for anywhere
# — only trust a standalone "By <Brand>" sentence, or "<Brand>" immediately
# following the product's own title text.
STANDALONE_BY_RE = re.compile(r"(?:^|\.\s+)By\s+([A-Z][A-Za-z&.' ]{2,25}?)\s*(?:\.|$)")
BRAND_STOPWORDS = {
    "the", "a", "an", "and", "for", "with", "both", "of", "is", "as",
    "description", "men", "women", "unisex", "discover",
}
BRAND_ALIASES = {"rasasi": "Rasasi", "al rasasi": "Rasasi", "ibraq": "Ibraq", "lattafa perfumes": "Lattafa"}
ML_RE = re.compile(r"(\d+)\s*ML", re.I)


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
            print(f"  {e.code} from darelarabia.com, waiting {wait}s and retrying "
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
    text = re.sub(r"</p>|<br\s*/?>|</div>", ". ", html or "", flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _is_plausible_brand(candidate: str) -> bool:
    words = candidate.split()
    if not words or len(words) > 4:
        return False
    return not any(w.lower() in BRAND_STOPWORDS for w in words)


def extract_brand(title: str, body_html: str) -> str:
    text = strip_html(body_html)
    brand = ""

    if title:
        # "<Title> by <Brand> is/,." — anchored to the product's own title
        # so it can't latch onto an unrelated "by" elsewhere in the prose.
        anchored_re = re.compile(re.escape(title) + r"\s+by\s+([A-Z][A-Za-z&.' ]{2,25}?)(?:\s+is\b|[.,]|$)", re.I)
        m = anchored_re.search(text)
        if m and _is_plausible_brand(m.group(1)):
            brand = m.group(1).strip()

    if not brand:
        m = STANDALONE_BY_RE.search(text)
        if m and _is_plausible_brand(m.group(1)):
            brand = m.group(1).strip()

    return BRAND_ALIASES.get(brand.lower(), brand)


def extract_ml(variants: list):
    for v in variants:
        opt = (v.get("option1") or v.get("title") or "")
        m = ML_RE.search(opt)
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

    ml = extract_ml(variants)
    if not ml:
        return None

    body_html = p.get("body_html") or ""
    brand = extract_brand(title, body_html)
    name_en = title
    if brand:
        name_en = strip_redundant_brand_suffix(name_en, brand)

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
         f"sync_darelarabia.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
