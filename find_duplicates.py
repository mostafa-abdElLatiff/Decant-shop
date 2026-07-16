#!/usr/bin/env python3
"""
find_duplicates.py — report likely duplicate products for manual review.

extract.py and sync_roseperfume.py both merge conservatively (only exact ID
or exact normalized-name matches) so they never silently merge two different
fragrances together. The tradeoff: a brand-suffix or naming difference (e.g.
"Jasmere Parfum" vs "French Avenue Jasmere Parfum") won't auto-merge and
becomes a near-duplicate entry instead. Run this occasionally to see what's
worth merging by hand — it only prints candidates, it changes nothing.

    python find_duplicates.py
"""
import json
from pathlib import Path

from extract import _tokens, CATALOG

STOP_BRAND_ONLY = {"perfumes", "perfume", "men", "women", "fragrances", "fragrance"}


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    products = catalog["products"]

    pairs = []
    seen = set()
    for i, a in enumerate(products):
        for b in products[i + 1:]:
            core_a, core_b = _tokens(a["name_en"]), _tokens(b["name_en"])
            if len(core_a) < 2 or len(core_b) < 2:
                continue
            full_a = _tokens(f"{a['name_en']} {a.get('brand', '')}")
            full_b = _tokens(f"{b['name_en']} {b.get('brand', '')}")
            if core_a == core_b or core_a <= full_b or core_b <= full_a:
                key = tuple(sorted([a["id"], b["id"]]))
                if key not in seen:
                    seen.add(key)
                    pairs.append((a, b))

    if not pairs:
        print("No candidate duplicates found.")
        return

    print(f"{len(pairs)} candidate pair(s) — review before merging, some are legitimately distinct products:\n")
    for a, b in pairs:
        stores_a = ", ".join(s["name"] for s in a.get("stores", []))
        stores_b = ", ".join(s["name"] for s in b.get("stores", []))
        print(f"  {a['id']!r} ({a['name_en']!r}, {a.get('brand','')!r}) [{stores_a}]")
        print(f"  {b['id']!r} ({b['name_en']!r}, {b.get('brand','')!r}) [{stores_b}]")
        print()


if __name__ == "__main__":
    main()
