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

from extract import _tokens, find_typo_candidates, CATALOG

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
    else:
        print(f"{len(pairs)} candidate pair(s) — review before merging, some are legitimately distinct products:\n")
        for a, b in pairs:
            stores_a = ", ".join(s["name"] for s in a.get("stores", []))
            stores_b = ", ".join(s["name"] for s in b.get("stores", []))
            print(f"  {a['id']!r} ({a['name_en']!r}, {a.get('brand','')!r}) [{stores_a}]")
            print(f"  {b['id']!r} ({b['name_en']!r}, {b.get('brand','')!r}) [{stores_b}]")
            print()

    # A different, narrower signal from the word-overlap scan above: two
    # products whose names are identical but for ONE word that's spelled
    # almost the same ("Nuctorno" vs "Nocturno") — a transcription typo on
    # one store's own listing, not a naming/brand-suffix difference. Never
    # auto-merged (see find_existing_product's docstring for why the
    # signal isn't reliable enough for that), so it's easy for one of
    # these to sit unnoticed for a while — surfaced here explicitly on
    # every run instead of only being caught by chance during a manual
    # scan like the "Nuctorno" one originally was.
    typo_pairs = find_typo_candidates(catalog)
    if typo_pairs:
        print(f"\n{len(typo_pairs)} possible spelling-typo pair(s) — same brand, one word barely differs "
              f"(verify it's really a typo before merging, e.g. via product images — some of these ARE "
              f"genuinely different products, like \"Cranberry Musk\" vs \"Raspberry Musk\"):\n")
        for a, b in typo_pairs:
            stores_a = ", ".join(s["name"] for s in a.get("stores", []))
            stores_b = ", ".join(s["name"] for s in b.get("stores", []))
            print(f"  {a['id']!r} ({a['name_en']!r}, {a.get('brand','')!r}) [{stores_a}]")
            print(f"  {b['id']!r} ({b['name_en']!r}, {b.get('brand','')!r}) [{stores_b}]")
            print()


if __name__ == "__main__":
    main()
