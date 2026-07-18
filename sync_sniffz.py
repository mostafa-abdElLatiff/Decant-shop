#!/usr/bin/env python3
"""
sync_sniffz.py — periodic, fully-automatic sync of sniffz-eg.com into
products.json. No AI/vision involved: like roseperfume.online, this store
runs on Shopify, which exposes a public JSON product API, so it's plain
structured-data parsing (title, vendor, variant prices/stock, and the
description text for notes and "dupe of" references — in English here, no
translation needed).

Covers three collections: summer-samples and winter-samples (decants) and
pre-order-full-bottles (full, sealed bottles — the collection's own name is
the explicit "sealed/new" evidence extract.py's rules ask for). Only
variants marked available on Shopify are included; a product with zero
available variants is skipped entirely — this is the "check availability
before adding" step.

Run whenever you want to refresh this store's listings:

    python sync_sniffz.py

Commits locally if anything changed — never pushes. Review with
`git log` / `git diff` and push yourself when ready.
"""
import json
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from extract import slugify, accord_color, find_existing_product, unique_id_for, reconcile_offers, is_web_sourced_hero, CATALOG  # noqa: E402
from brand_prefixes import split_brand_prefix, split_brand_suffix  # noqa: E402

BASE_URL = "https://sniffz-eg.com"
STORE_NAME = "sniffz"
STORE_URL = "https://sniffz-eg.com/"
STORE_SLUG = slugify(STORE_NAME)
IMAGES_DIR = CATALOG.parent / "images"

# (collection handle, offer kind)
COLLECTIONS = [
    ("summer-samples", "decant"),
    ("winter-samples", "decant"),
    ("pre-order-full-bottles", "full"),
]


def fetch_url(url: str, attempts: int = 5) -> bytes:
    """sniffz-eg.com has been observed going down with a transient 503
    (Retry-After header, not a bot block) — retry with backoff instead of
    failing the whole run over what's usually a temporary blip."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code != 503 or attempt == attempts - 1:
                raise
            wait = int(e.headers.get("Retry-After", 30 * (attempt + 1)))
            print(f"  503 from sniffz-eg.com, waiting {wait}s and retrying "
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


def extract_notes(body_html: str):
    """Pull the comma-separated note list following each "X Notes:" label.
    Slices the raw HTML up to whichever comes first — the next label, or the
    end of the enclosing <li>/<p> block — before stripping tags, so a label
    with nothing but a closing tag right after it doesn't bleed into the
    next label's list, and the last label doesn't bleed into the prose that
    follows the notes block."""
    notes, seen = [], set()
    for label in ("Top Notes", "Middle Notes", "Base Notes"):
        idx = body_html.find(label)
        if idx == -1:
            continue
        window = body_html[idx:idx + 600]
        stops = [m.start() for m in re.finditer(r"</(?:li|p)>|Top Notes|Middle Notes|Base Notes", window[len(label):])]
        end = min(stops) + len(label) if stops else len(window)
        chunk = re.sub(r"<[^>]+>", " ", window[:end])
        chunk = re.sub(r"\s+", " ", chunk).strip()
        chunk = re.sub(rf"^{label}:?\s*", "", chunk, flags=re.I)
        for tok in chunk.split(","):
            tok = tok.strip().rstrip(".")
            # a note can legitimately appear in more than one of Top/Middle/
            # Base (e.g. Bergamot in both top and base) — keep only the
            # first mention so it doesn't show as a duplicated accord bar
            if tok and tok.lower() not in seen:
                seen.add(tok.lower())
                notes.append(tok)
    return notes


def extract_dupe(body_html: str):
    text = re.sub(r"<[^>]+>", " ", body_html)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"dupe of\s+(?:the\s+)?(.+?)(?:[,.]|—|–| which| capturing| offering|$)", text, re.I)
    if not m:
        return None
    raw = m.group(1).strip()

    m2 = re.match(r"^(.+?)\s+by\s+(.+)$", raw, re.I)
    if m2:
        return f"{m2.group(1).strip()} — {m2.group(2).strip()}"

    rest, brand = split_brand_prefix(raw)
    if brand:
        return f"{rest} — {brand}"
    rest, brand = split_brand_suffix(raw)
    if brand:
        return f"{rest} — {brand}"
    return raw


def download_image(url, dest_path):
    dest_path.write_bytes(fetch_url(url))


def parse_product(p, kind: str):
    available_variants = [v for v in p["variants"] if v["available"]]
    if not available_variants:
        return None

    title = p["title"].strip()
    title = re.sub(r"\s*Full\s*&\s*Sealed\s*$", "", title, flags=re.I).strip()
    name_en, brand = split_brand_prefix(title)

    offers = []
    for v in available_variants:
        m = re.search(r"(\d+)\s*ml", v["title"], re.I)
        if not m:
            continue
        offers.append({"kind": kind, "ml": int(m.group(1)), "price": int(float(v["price"]))})
    if not offers:
        return None

    dupe = extract_dupe(p["body_html"])
    notes = extract_notes(p["body_html"])

    return {
        "name_en": name_en or title,
        "brand": brand,
        "dupe_of": dupe,
        "notes": notes,
        "image": p["images"][0]["src"] if p["images"] else "",
        "product_url": f"{STORE_URL.rstrip('/')}/products/{p['handle']}" if p.get("handle") else None,
        "offers": sorted(offers, key=lambda o: o["ml"]),
    }


def main():
    parsed_by_name = {}
    for handle, kind in COLLECTIONS:
        print(f"Fetching collection '{handle}' ...")
        raw = fetch_collection(handle)
        print(f"  {len(raw)} products")
        for p in raw:
            info = parse_product(p, kind)
            if not info:
                continue
            key = info["name_en"]
            if key in parsed_by_name:
                parsed_by_name[key]["offers"].extend(info["offers"])
            else:
                parsed_by_name[key] = info

    print(f"Total qualifying (in-stock) products: {len(parsed_by_name)}")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}
    IMAGES_DIR.mkdir(exist_ok=True)
    added, synced = 0, 0

    for name_en, info in parsed_by_name.items():
        product = find_existing_product(catalog, name_en, info["brand"])
        if product is None:
            accords = [
                {"label_en": n, "label_ar": "", "color": accord_color(n), "w": max(40, 100 - i * 10)}
                for i, n in enumerate(info["notes"])
            ]
            product = {
                "id": unique_id_for(catalog, name_en, info["brand"]),
                "name_ar": "",
                "name_en": name_en,
                "brand": info["brand"],
                "dupe_of": [info["dupe_of"]] if info["dupe_of"] else [],
                "image": "",
                "accords": accords,
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
        # info["offers"] is this listing's FULL current offer set for this
        # run, so reconcile (not just upsert) — a size that's dropped out
        # gets marked "sold" and, if it stays that way for a week without
        # restocking, dropped for good.
        store["offers"] = reconcile_offers(store["offers"], info["offers"])
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
        ["git", "commit", "-m", f"sync_sniffz.py: {added} added, {synced} synced"],
        cwd=CATALOG.parent, check=True,
    )
    print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")


if __name__ == "__main__":
    main()
