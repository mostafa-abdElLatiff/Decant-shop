#!/usr/bin/env python3
"""
sync_roseperfume.py — periodic, fully-automatic sync of roseperfume.online's
men's fragrances collection into products.json. No AI/vision involved: the
store runs on Shopify, which exposes a public JSON product API, so this is
plain structured-data parsing (product title, tags, variant prices/stock,
and the Arabic description's dupe-reference / notes-pyramid sections).

Run manually whenever you want to refresh this store's listings. Each run:
  1. Fetches the full men's-fragrances product list.
  2. Skips non-fragrance items (deodorants, body splashes, gift sets) and
     anything with no in-stock variant.
  3. Only includes variants that are actually purchasable right now — a
     product with some sizes in stock and others sold out only gets the
     in-stock ones.
  4. For each product it can confidently re-identify (exact ID, or an exact
     normalized-name match), fully replaces roseperfume's offers with the
     current state, so a decant size that's gone out of stock is dropped.
     Deliberately never removes a roseperfume listing it can't re-match —
     see the comment on replace_store_offers() for why. Run
     find_duplicates.py periodically to catch near-duplicates and stale
     listings for manual cleanup instead.
  5. Commits locally if anything changed — never pushes. Review with
     `git log` / `git diff` and push yourself when ready.

Run manually any time with:  python3 sync_roseperfume.py
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import slugify, accord_color, find_existing_product, unique_id_for, reconcile_offers, is_web_sourced_hero, strip_redundant_brand_suffix, CATALOG  # noqa: E402
from rp_notes import translate_note, split_dupe  # noqa: E402

COLLECTION_URL = "https://roseperfume.online/collections/men-fragrances/products.json"
STORE_NAME = "roseperfume"
STORE_URL = "https://roseperfume.online/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"

NON_PERFUME_KW = ["deodorant", "body splash", "body spray", "gift set", "gift box", " box"]

# Shopify tags mix a product's actual brand in with generic category/
# marketing labels, in no reliable order (a real brand is just as likely to
# be tags[1] as tags[0]) — these are the category tags observed on this
# collection, skipped when picking which tag is the brand.
GENERIC_TAGS = {
    "men fragrances", "women fragrances", "unisex fragrances",
    "saudi arabia perfumes", "deodorant", "luxury perfume",
    "concentrated perfume oils", "best selling",
}


# A brand tag spelled with no internal spaces ("ALREHAB") tokenizes as one
# solid word and can't token-match the catalog's existing spaced spelling
# ("Al Rehab") from other stores — _brands_match() then treats them as two
# different houses and silently creates a duplicate product. Normalize the
# ones actually seen rather than relying on token-matching to bridge it.
BRAND_ALIASES = {"alrehab": "Al Rehab", "al-rehab": "Al Rehab"}


def pick_brand_tag(tags: list) -> str:
    for t in tags or []:
        if t.strip().lower() not in GENERIC_TAGS:
            return BRAND_ALIASES.get(t.strip().lower(), t)
    return ""


def fetch_url(url: str, attempts: int = 5) -> bytes:
    """roseperfume.online has been observed going down with a transient 503
    (same as sniffz-eg.com) — retry with backoff instead of failing the
    whole run over what's usually a temporary blip."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code != 503 or attempt == attempts - 1:
                raise
            wait = int(e.headers.get("Retry-After", 30 * (attempt + 1)))
            print(f"  503 from roseperfume.online, waiting {wait}s and retrying "
                  f"({attempt + 1}/{attempts})...")
            time.sleep(wait)


def fetch_all_products() -> list:
    products = []
    page = 1
    while True:
        data = json.loads(fetch_url(f"{COLLECTION_URL}?limit=250&page={page}"))
        batch = data.get("products", [])
        if not batch:
            break
        products.extend(batch)
        page += 1
    return products


def is_non_perfume(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in NON_PERFUME_KW)


def extract_field(body: str, label: str):
    m = re.search(rf"{re.escape(label)}\s*[:：]?\s*</p>\s*<p[^>]*>\s*([^<]*?)\s*</p>", body)
    return m.group(1).strip() if m else None


def extract_dupe(body: str):
    m = re.search(r"بديل لعطر\s*</p>\s*<p[^>]*>\s*([^<]*?)\s*</p>", body)
    return m.group(1).strip() if m else None


def split_phrase(phrase):
    if not phrase:
        return []
    parts = re.split(r"[,،]|\sو(?=[؀-ۿ])", phrase)
    out = []
    for part in parts:
        t = part.strip().strip(".").strip()
        t = re.sub(r"^و", "", t).strip()
        if t:
            out.append(t)
    return out


def build_notes(top, mid, base):
    tokens = split_phrase(top) + split_phrase(mid) + split_phrase(base)
    seen, notes = set(), []
    for tok in tokens:
        en = translate_note(tok)
        if not en or en in seen:
            continue
        seen.add(en)
        notes.append((en, tok))
    return notes


def parse_product(p):
    """Return a normalized dict, or None if this listing doesn't qualify
    (non-fragrance item, or nothing currently purchasable)."""
    if is_non_perfume(p["title"]):
        return None

    variants = p["variants"]
    if len(variants) == 1:
        v = variants[0]
        if not v["available"]:
            return None
        size_m = re.search(r"(\d{2,3})\s*ML", p["body_html"], re.I)
        if not size_m:
            return None
        offers = [{"kind": "full", "ml": int(size_m.group(1)), "price": int(float(v["price"]))}]
    else:
        offers = []
        for v in variants:
            if not v["available"]:
                continue
            t = v["title"].lower()
            m = re.search(r"(\d+)\s*ml", t)
            ml = int(m.group(1)) if m else None
            if ml:
                kind = "full" if "full" in t else "decant"
                offers.append({"kind": kind, "ml": ml, "price": int(float(v["price"]))})
        if not offers:
            return None

    body = p["body_html"]
    notes = build_notes(
        extract_field(body, ":المكونات العليا"),
        extract_field(body, ":المكونات الوسطى"),
        extract_field(body, ":المكونات الأساسية"),
    )
    dupe_raw = extract_dupe(body)
    brand = pick_brand_tag(p["tags"])
    # the title sometimes redundantly restates the brand as a "... By
    # <Brand>" suffix even though it's already in its own tag ("Khumar
    # Zanzibar By Wadi Al khaleej", brand tag "Wadi Al Khaleej") — left
    # in, that beats find_existing_product's matching (an extra "by"
    # token in the name that the already-split sibling doesn't have) and
    # silently duplicates the product on every re-sync. Unlike
    # strip_redundant_brand_suffix() elsewhere (which deliberately leaves
    # a "By <Brand>" suffix alone — could be a real designer collab name),
    # on this store's own title convention "By X" always just means
    # attribution, so strip it outright before the general pass.
    name_en = p["title"].strip()
    if brand and name_en.lower().endswith(f"by {brand.lower()}"):
        name_en = name_en[: -(len(brand) + 3)].rstrip(" -—–|,").strip()
    name_en = strip_redundant_brand_suffix(name_en, brand) if brand else name_en

    return {
        "name_en": name_en,
        "brand": brand,
        "dupe_of": split_dupe(dupe_raw) if dupe_raw else None,
        "notes": notes,
        "image": p["images"][0]["src"] if p["images"] else "",
        "product_url": f"{STORE_URL.rstrip('/')}/products/{p['handle']}" if p.get("handle") else None,
        "offers": sorted(offers, key=lambda o: o["ml"]),
    }


def download_image(url, dest_path):
    dest_path.write_bytes(fetch_url(url))


def replace_store_offers(product: dict, offers: list, image_rel: str = None, product_url: str = None):
    """Reconcile this store's offers against what's actually in stock this
    run — a size that's gone out of stock gets marked "sold" (and, if it
    stays that way for a week without restocking, dropped for good) rather
    than either staying stale forever or vanishing the instant it's gone —
    but only ever called on a product we positively re-identified this run.

    Deliberately NOT symmetric: this script never removes a roseperfume
    listing from a product it *couldn't* re-identify this run. The matching
    in find_existing_product is conservative on purpose (see extract.py) —
    it won't recognize e.g. "9PM Elixir Afnan" as the same product as a
    manually-merged "9pm Elixir", since that's exactly the brand-suffix
    mismatch a stricter check exists to avoid false-merging on. Doing
    removal on "wasn't matched this run" would silently strip roseperfume's
    listing from the correct, already-deduplicated product every single run
    and recreate a duplicate instead — worse than just leaving a stale
    listing. Run find_duplicates.py periodically to catch genuinely
    discontinued listings by hand instead.
    """
    product.setdefault("stores", [])
    store = next((s for s in product["stores"] if s["name"] == STORE_NAME), None)
    if store is None:
        store = {"name": STORE_NAME, "url": STORE_URL, "offers": []}
        product["stores"].append(store)
    store["offers"] = reconcile_offers(store["offers"], offers)
    if image_rel:
        store["image"] = image_rel
    if product_url:
        store["product_url"] = product_url


def main():
    print(f"Fetching {COLLECTION_URL} ...")
    raw_products = fetch_all_products()
    print(f"  {len(raw_products)} products in collection")

    parsed = {}
    for p in raw_products:
        info = parse_product(p)
        if info:
            parsed[info["name_en"]] = info
    print(f"  {len(parsed)} qualify (in-stock fragrance listings with readable sizes)")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}

    IMAGES_DIR.mkdir(exist_ok=True)
    added, synced = 0, 0
    matched_ids = set()

    for name_en, info in parsed.items():
        product = find_existing_product(catalog, name_en, info["brand"])
        if product is None:
            product = {
                "id": unique_id_for(catalog, name_en, info["brand"]),
                "name_ar": "",
                "name_en": name_en,
                "brand": info["brand"],
                "dupe_of": [info["dupe_of"]] if info["dupe_of"] else [],
                "image": "",
                "accords": [
                    {"label_en": en, "label_ar": ar, "color": accord_color(en), "w": max(40, 100 - i * 10)}
                    for i, (en, ar) in enumerate(info["notes"])
                ],
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

        replace_store_offers(product, info["offers"], image_rel=store_image_rel, product_url=info.get("product_url"))
        matched_ids.add(product["id"])
        synced += 1

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {added} new products, {synced} product listings synced (incl. new). "
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
         f"sync_roseperfume.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
