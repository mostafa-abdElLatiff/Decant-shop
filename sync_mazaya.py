#!/usr/bin/env python3
"""sync_mazaya.py — periodic, fully-automatic sync of mazaya.eg into
products.json. Not Shopify — a custom Nuxt.js storefront backed by a
Magento 2 GraphQL API at backend.mazaya.eg/graphql (no auth needed, plain
POST). Only sells full bottles (no decant/leftover options), confirmed by
the user.

Covers two categories, queried by their GraphQL category_uid: men (uid
"Mzk=") and unisex (uid "NTA5" — note the unisex url_key resolves to TWO
categories on this store, one real (347 products, matches the live
/en/unisex page) and one decoy with 0 products; "NTA5" is the real one,
confirmed by hand, so it's hardcoded here rather than re-resolved by
url_key on every run).

Two product shapes:
  - SimpleProduct: one fixed size, stated only in the product `name`
    (e.g. "BBY HERO ELIXR PERFUM 60ML") — parsed via a trailing-ml regex
    and stripped from the name, same as a single-variant Shopify listing.
  - ConfigurableProduct: real size variants, each with its own `product`
    sub-object (price, sku) and an `attributes[].label` giving the size
    directly (e.g. "200 ML") — no regex needed for these.

`brand.name` is a real structured field (unlike darelarabia/emaratiscents,
which have to guess brand from description text) but comes back ALL CAPS
("YVES SAINT LAURENT") — same problem sync_perfuzone.py has with Shopify
titles, so smart_title() is reused verbatim for both brand and name.

`stock_status` ("IN_STOCK"/"OUT_OF_STOCK") is a real field too. A sold-out
listing is still synced (with its price) rather than skipped —
reconcile_offers() marks it "sold" immediately instead of dropping it, so
an out-of-stock size still tells you what this store charges and is worth
waiting for a restock at.

Run manually any time with:  python3 sync_mazaya.py
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

STORE_NAME = "mazaya"
STORE_URL = "https://mazaya.eg/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"
GRAPHQL_URL = "https://backend.mazaya.eg/graphql"
CATEGORY_UIDS = ["Mzk=", "NTA5"]  # men, unisex
PAGE_SIZE = 250

QUERY = """
query($uid: String!, $page: Int!, $size: Int!) {
  products(filter: {category_uid: {eq: $uid}}, pageSize: $size, currentPage: $page) {
    total_count
    page_info { current_page total_pages }
    items {
      id name sku url_key __typename stock_status
      brand { name }
      price_range { minimum_price { final_price { value currency } } }
      small_image { url }
      ... on ConfigurableProduct {
        variants {
          attributes { label }
          product { id sku stock_status price_range { minimum_price { final_price { value } } } }
        }
      }
    }
  }
}
"""

KEEP_UPPER = {"pm", "am", "edp", "edt", "vip", "ysl", "jpg", "dg", "mfk", "uk", "usa", "ck"}
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


# Unlike Feel22/Shopify titles, a SimpleProduct's size mention is often
# NOT at the very end — it's routinely followed by junk tags the store
# appends after it ("100ML VAPO", "105ML EDP", "100 ML NEW", "75ML.") —
# so this searches anywhere and everything from the match onward (size
# plus whatever trails it) is dropped, not just a trailing "NNml". Also
# tolerates "mI" (capital I) in place of "ml" — a real, recurring typo in
# this store's own data entry (I/l look identical in their font), e.g.
# "125mI", "75mI" — unambiguous in a fragrance-size context, not a guess.
ML_ANY_RE = re.compile(r"(\d+)\s*m[li]\b", re.I)
ML_LABEL_RE = re.compile(r"(\d+)\s*m[li]", re.I)

# same generic-marketing-boilerplate situation as sync_feel22.py's
# GENDER_MARKETING_RE — this store tags a chunk of listings "FOR MEN"/"FOR
# WOMEN" too, not as part of the real product name.
GENDER_MARKETING_RE = re.compile(r"\s*\bfor\s+(?:men|him|her|women)\b\s*", re.I)


def fetch_page(uid: str, page: int, attempts: int = 5) -> dict:
    payload = json.dumps({"query": QUERY, "variables": {"uid": uid, "page": page, "size": PAGE_SIZE}}).encode()
    req = urllib.request.Request(
        GRAPHQL_URL, data=payload,
        headers={"Content-Type": "application/json", "Store": "en", "User-Agent": "Mozilla/5.0"},
    )
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except (urllib.error.HTTPError, urllib.error.URLError) as e:
            if attempt == attempts - 1:
                raise
            wait = 30 * (attempt + 1)
            print(f"  {e} from backend.mazaya.eg, waiting {wait}s and retrying "
                  f"({attempt + 1}/{attempts})...")
            time.sleep(wait)


def fetch_category(uid: str) -> list:
    items, page = [], 1
    while True:
        data = fetch_page(uid, page)
        block = data.get("data", {}).get("products") or {}
        batch = block.get("items", [])
        if not batch:
            break
        items.extend(batch)
        total_pages = block.get("page_info", {}).get("total_pages", page)
        if page >= total_pages:
            break
        page += 1
    return items


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
            time.sleep(wait)


def download_image(url, dest_path):
    dest_path.write_bytes(fetch_url(url))


def parse_product(p: dict):
    raw_name = (p.get("name") or "").strip()
    if not raw_name:
        return None
    # strip early, same rationale as sync_feel22.py: it can otherwise
    # strand itself after a size mention and get in the way of the
    # size/brand parsing below.
    raw_name = GENDER_MARKETING_RE.sub(" ", raw_name).strip()
    raw_name = re.sub(r"\s+", " ", raw_name)

    brand_raw = ((p.get("brand") or {}).get("name") or "").strip()
    brand = smart_title(brand_raw) if brand_raw.isupper() else brand_raw

    name_en = raw_name
    is_all_upper = raw_name.isupper()

    offers = []
    if p.get("__typename") == "ConfigurableProduct":
        for v in p.get("variants") or []:
            attrs = v.get("attributes") or []
            label = attrs[0]["label"] if attrs else ""
            m = ML_LABEL_RE.search(label)
            if not m:
                continue
            ml = int(m.group(1))
            vp = v.get("product") or {}
            price_val = ((vp.get("price_range") or {}).get("minimum_price") or {}).get("final_price", {}).get("value")
            if not price_val:
                continue
            price = round(float(price_val))
            if price <= 0:
                continue
            available = vp.get("stock_status") == "IN_STOCK"
            offers.append({"kind": "full", "ml": ml, "price": price, "available": available})
        # the parent's own `name` never carries a size for configurables
        # (e.g. "One NIGHT ESSENCE PERFUM"), so nothing to strip.
    else:
        m = ML_ANY_RE.search(raw_name)
        if not m:
            return None
        ml = int(m.group(1))
        name_en = raw_name[:m.start()].strip(" -")
        name_en = re.sub(r"\s+", " ", name_en).strip()
        price_val = ((p.get("price_range") or {}).get("minimum_price") or {}).get("final_price", {}).get("value")
        if not price_val:
            return None
        price = round(float(price_val))
        if price <= 0:
            return None
        available = p.get("stock_status") == "IN_STOCK"
        offers.append({"kind": "full", "ml": ml, "price": price, "available": available})

    if not offers:
        return None

    if is_all_upper:
        name_en = smart_title(name_en)
    if brand:
        name_en = strip_redundant_brand_suffix(name_en, brand)
    if not name_en:
        return None

    image = ((p.get("small_image") or {}).get("url") or "").split("?")[0]
    return {
        "name_en": name_en,
        "brand": brand,
        "image": image,
        "product_url": f"{STORE_URL.rstrip('/')}/en/{p['url_key']}" if p.get("url_key") else None,
        "offers": offers,
        "mazaya_id": p.get("id"),
    }


def main():
    seen_ids = set()
    parsed = []
    for uid in CATEGORY_UIDS:
        print(f"Fetching category_uid '{uid}' ...")
        raw = fetch_category(uid)
        print(f"  {len(raw)} listing(s)")
        for p in raw:
            if p.get("id") in seen_ids:
                continue
            info = parse_product(p)
            if not info:
                continue
            seen_ids.add(p.get("id"))
            parsed.append(info)
    print(f"{len(parsed)} qualifying listing(s) across both categories")

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
        ["git", "commit", "-m", f"sync_mazaya.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
