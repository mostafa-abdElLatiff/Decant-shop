#!/usr/bin/env python3
"""Generate a small static HTML file per product in products/<id>.html.

These are NOT full copies of the interactive app -- they're thin
redirect shims that exist for one reason: WhatsApp/Facebook/Twitter/Slack
link-unfurl bots read only the raw HTML <head> of the exact URL they
fetch. They don't execute JavaScript and don't follow client-side
redirects, so a real static file with real Open Graph/Twitter meta tags
is required for a correct share preview -- there's no other way to get
that on a backend-less GitHub Pages site. A real human visitor who opens
the link gets redirected instantly into index.html, where the existing
hash-routing (openProductModal in index.html) opens the same product's
modal automatically.

Run this after any products.json edit -- normally that's automatic via
.github/workflows/generate-product-pages.yml (triggered on any push that
touches products.json, so it also covers admin.html edits, which commit
straight to the repo via the GitHub API and never run a local script).
"""
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
CATALOG = ROOT / "products.json"
OUT_DIR = ROOT / "products"
BASE_URL = "https://mostafa-abdellatiff.github.io/Decant-shop/"


def cheapest_price(p):
    prices = [o["price"] for s in p.get("stores", []) for o in s.get("offers", [])
              if not o.get("sold_since")]
    return min(prices) if prices else None


def store_count(p):
    return len({s["name"] for s in p.get("stores", []) if s.get("offers")})


def page_html(p):
    name = p.get("name_en") or p.get("name_ar") or p["id"]
    brand = p.get("brand") or ""
    title = f"{name} — {brand}" if brand else name
    price = cheapest_price(p)
    stores = store_count(p)
    if price is not None and stores:
        desc = f"Compare prices for {name} across {stores} store{'s' if stores != 1 else ''}, from {price} EGP."
    else:
        desc = f"Compare prices for {name} across Egypt's fragrance decant stores."
    page_url = f"{BASE_URL}products/{p['id']}.html"
    target = f"../index.html#{p['id']}"
    image_url = f"{BASE_URL}{p['image']}" if p.get("image") else ""

    t = html.escape(title)
    d = html.escape(desc)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{html.escape(page_url)}">
<link rel="icon" href="{BASE_URL}favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="{BASE_URL}apple-touch-icon.png">
<meta property="og:type" content="product">
<meta property="og:title" content="{t}">
<meta property="og:description" content="{d}">
<meta property="og:url" content="{html.escape(page_url)}">
{f'<meta property="og:image" content="{html.escape(image_url)}">' if image_url else ""}
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{t}">
<meta name="twitter:description" content="{d}">
{f'<meta name="twitter:image" content="{html.escape(image_url)}">' if image_url else ""}
<meta http-equiv="refresh" content="0; url={html.escape(target)}">
<script>location.replace({json.dumps(target)});</script>
</head>
<body>
<p>Redirecting to <a href="{html.escape(target)}">{t} — full price comparison</a>…</p>
</body>
</html>
"""


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    products = catalog.get("products", [])
    OUT_DIR.mkdir(exist_ok=True)

    current_ids = set()
    for p in products:
        current_ids.add(p["id"])
        (OUT_DIR / f"{p['id']}.html").write_text(page_html(p), encoding="utf-8")

    # remove pages for products that no longer exist (merged/removed since
    # the last run) -- otherwise stale share links would silently pile up
    removed = 0
    for f in OUT_DIR.glob("*.html"):
        if f.stem not in current_ids:
            f.unlink()
            removed += 1

    print(f"Generated {len(products)} product page(s), removed {removed} stale one(s).")

    status = subprocess.run(
        ["git", "status", "--porcelain", "products/"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        print("No changes to commit.")
        return

    subprocess.run(["git", "add", "products/"], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "commit", "-m", f"generate_product_pages.py: {len(products)} page(s), {removed} removed"],
        cwd=ROOT, check=True,
    )
    print("Committed locally.")


if __name__ == "__main__":
    sys.exit(main())
