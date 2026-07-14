#!/usr/bin/env python3
"""
extract.py — turn perfume post images into wishlist entries.

Every run is tied to one store (where you saw the offer), so pass --store and
--url alongside the image(s):

    # --- Gemini (cloud, free tier has daily limits) ---
    pip install google-genai
    export GEMINI_API_KEY="..."        # free key from https://aistudio.google.com/apikey
    python extract.py --store "Ahmed Perfumes" --url "https://facebook.com/ahmedperfumes" image.jpg
    python extract.py --store "Ahmed Perfumes" --url "https://facebook.com/ahmedperfumes" posts/

    # --- Ollama (local, offline, no limits — can be slow depending on hardware) ---
    brew install ollama
    ollama pull llama3.2-vision        # one-time ~8 GB download
    python extract.py --local --store "..." --url "..." image.jpg

    # Facebook post URL (downloads ALL images automatically via gallery-dl):
    python extract.py --store "..." --url "..." "https://www.facebook.com/groups/.../posts/..."

    # Facebook CDN URLs (right-click image → Copy Image Address):
    python extract.py --store "..." --url "..." "https://scontent-*.fbcdn.net/..."

For each image, extracts the fragrance name, brand, what it's a dupe of (if
stated), Fragrantica-style notes, and sizes/prices — then merges it into
products.json as an offer under the given store. If the fragrance already
exists (matched by slugified name), the store is added or its offers updated
in place; otherwise a new product entry is created.
Review with `git diff`, commit & push — GitHub Pages redeploys the site.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import tempfile
from pathlib import Path

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2-vision")
OLLAMA_URL   = "http://localhost:11434/api/generate"

CATALOG = Path(__file__).parent / "products.json"
MODEL = "gemini-2.0-flash-lite"  # highest free-tier quota
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VALID_KINDS = {"decant", "full", "leftover"}

PALETTE = ["#F5F0A9", "#D96B3B", "#C98B5E", "#E86A6A", "#A8D18D",
           "#B9A8E0", "#8A6242", "#EDF0F7", "#F3E97A", "#D8A45B"]

PROMPT = """You are extracting a perfume listing from a social media post image
for a perfume decant catalogue. The image usually contains the fragrance name
(often in both English and Arabic), size/price lines like "10 ml = 220"
(prices in EGP), sometimes colored accord bars with note labels, and
sometimes a mention of which original/designer fragrance this one is a dupe
of ("انسباير من", "دوب لـ", "inspired by", etc).

Return ONLY valid JSON, no markdown fences, matching exactly this schema:
{
  "name_en": "English fragrance name incl. brand, empty string if absent",
  "name_ar": "Arabic fragrance name, empty string if absent",
  "brand": "brand name in English, empty string if not visible",
  "dupe_of": ["name of the original fragrance(s) this is a dupe/clone of, empty list if none stated"],
  "type": "decant" or "full" or "leftover",
  "sizes": [{"ml": 3, "price": 100}],
  "notes": [{"label_en": "English note name", "label_ar": "Arabic note label if shown, else empty string"}]
}

Rules:
- "type": decant for ml-sized splits; full for sealed/complete bottles;
  leftover for the remainder of a decanted bottle (باقي/بواقي التقسيم).
- Include every size/price pair you can read. Prices are integers in EGP.
- "dupe_of" only if the post explicitly says this is inspired by / a dupe of
  another named fragrance — do not guess.
- List notes top to bottom in order of prominence if accord bars are visible,
  else [].
- Do not invent data you cannot read from the image."""


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or f"p-{int(time.time())}"


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def is_facebook_url(s: str) -> bool:
    return "facebook.com" in s and ("/posts/" in s or "story_fbid" in s or "permalink" in s)


def download_facebook_post(url: str) -> list:
    """Use gallery-dl to download all images from a Facebook post."""
    if not shutil.which("gallery-dl"):
        sys.exit(
            "gallery-dl is required for Facebook URLs.\n"
            "Install it with:  brew install gallery-dl"
        )
    tmp_dir = Path(tempfile.mkdtemp())
    print(f"  fetching all images from Facebook post...")
    succeeded = False
    for browser in ("chrome", "firefox", "safari", "chromium", "edge"):
        result = subprocess.run(
            ["gallery-dl", f"--cookies-from-browser={browser}",
             "--directory", str(tmp_dir), url],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            succeeded = True
            break
        # If the error isn't about the browser, stop trying others
        if "browser" not in result.stderr.lower() and "cookie" not in result.stderr.lower():
            break
    if not succeeded:
        print(f"  ✗ gallery-dl failed: {result.stderr.strip()[:200]}")
        return []
    images = sorted(f for f in tmp_dir.rglob("*") if f.suffix.lower() in IMAGE_EXTS)
    print(f"  found {len(images)} image(s) in post")
    return images


def download_url(url: str) -> Path:
    """Download a single image URL to a temp file and return its Path."""
    ext = ".jpg"
    for e in IMAGE_EXTS:
        if e in url.lower():
            ext = e
            break
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        tmp.write(resp.read())
    tmp.close()
    return Path(tmp.name)


def collect_images(args):
    paths = []  # list of (Path, display_label_or_None)
    for a in args:
        if is_facebook_url(a):
            print(f"→ Facebook post: {a}")
            paths += [(img, None) for img in download_facebook_post(a)]
        elif is_url(a):
            print(f"→ image URL: {a[:80]}...")
            try:
                paths.append((download_url(a), None))
            except Exception as e:
                print(f"  ✗ could not download: {e}")
        else:
            p = Path(a)
            if p.is_dir():
                paths += [(f, f) for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXTS]
            elif p.suffix.lower() in IMAGE_EXTS:
                paths.append((p, p))
            else:
                print(f"  skipping (not an image): {p}")
    return paths


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    return json.loads(text)


def to_product(raw: dict, image_rel: str) -> dict:
    notes = [
        {
            "label_en": n.get("label_en") or n.get("label_ar") or "",
            "label_ar": n.get("label_ar") or "",
            "color": PALETTE[i % len(PALETTE)],
            "w": max(40, 100 - i * 14),
        }
        for i, n in enumerate(raw.get("notes") or [])
    ]
    return {
        "id": slugify(raw.get("name_en") or raw.get("name_ar") or ""),
        "name_ar": raw.get("name_ar") or raw.get("name_en") or "",
        "name_en": raw.get("name_en") or "",
        "brand": raw.get("brand") or "",
        "dupe_of": [d for d in (raw.get("dupe_of") or []) if d],
        "image": image_rel,
        "accords": notes,
    }


def to_offers(raw: dict) -> list:
    kind = raw.get("type") if raw.get("type") in VALID_KINDS else "decant"
    return sorted(
        [{"kind": kind, "ml": int(s["ml"]), "price": int(s["price"])}
         for s in raw.get("sizes", []) if s.get("ml") and s.get("price")],
        key=lambda s: s["ml"],
    )


def merge_store(product: dict, store_name: str, store_url: str, offers: list):
    """Find-or-create the named store on product, then merge offers into it
    (replace matches on kind+ml, append otherwise)."""
    store = next(
        (s for s in product["stores"] if s["name"].strip().lower() == store_name.strip().lower()),
        None,
    )
    if store is None:
        store = {"name": store_name, "url": store_url, "offers": []}
        product["stores"].append(store)
    elif store_url:
        store["url"] = store_url

    for offer in offers:
        idx = next(
            (i for i, o in enumerate(store["offers"])
             if o["kind"] == offer["kind"] and o["ml"] == offer["ml"]),
            None,
        )
        if idx is not None:
            store["offers"][idx] = offer
        else:
            store["offers"].append(offer)


def gemini_generate(client, img_path: Path) -> str:
    uploaded = client.files.upload(file=img_path)
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=MODEL, contents=[PROMPT, uploaded])
            return resp.text
        except Exception as ex:
            err = str(ex)
            if "429" not in err:
                raise
            if "PerDay" in err or "per_day" in err.lower():
                sys.exit(
                    "\n✗ Daily free-tier quota exhausted.\n"
                    "  Options:\n"
                    "  1. Wait until tomorrow (UTC midnight) for quota to reset.\n"
                    "  2. Enable billing at https://console.cloud.google.com/billing\n"
                    "     (costs ~$0.01 per 100 images — essentially free).\n"
                    "  3. Run with --local to use Ollama offline (no limits, but can be\n"
                    "     very slow on modest hardware)."
                )
            if attempt < 2:
                wait = (attempt + 1) * 10
                print(f"  ⏳ rate limit — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def ollama_generate(img_path: Path) -> str:
    import base64
    img_b64 = base64.b64encode(img_path.read_bytes()).decode()
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": PROMPT,
        "images": [img_b64],
        "stream": False,
    }).encode()
    req = urllib.request.Request(
        OLLAMA_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read())["response"]
    except OSError:
        sys.exit(
            f"\n✗ Cannot reach Ollama at {OLLAMA_URL}.\n"
            "  Start it with:  ollama serve\n"
            f"  Pull the model: ollama pull {OLLAMA_MODEL}"
        )


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--store", required=True, help="Name of the store/seller this offer is from")
    parser.add_argument("--url", default="", help="Link to the store/seller (website or Facebook profile)")
    parser.add_argument("sources", nargs="+", help="Image file(s), folder(s), or Facebook/image URL(s)")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ns = parser.parse_args()

    client = None
    if ns.local:
        print(f"  using local model: {OLLAMA_MODEL}  (ollama)")
    else:
        try:
            from google import genai
        except ImportError:
            sys.exit("Missing package. Run:  pip install google-genai")
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            sys.exit("Set GEMINI_API_KEY  or use --local for offline mode.")
        client = genai.Client(api_key=api_key)

    images = collect_images(ns.sources)
    if not images:
        sys.exit("No images found.")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}

    added, updated, failed = 0, 0, 0

    for img, original in images:
        label = original.name if original else img.name
        print(f"→ {label}")
        try:
            text = ollama_generate(img) if ns.local else gemini_generate(client, img)
            raw = parse_json(text)

            offers = to_offers(raw)
            if not offers:
                print("  ⚠ no sizes/prices found — skipped (check the image)")
                failed += 1
                continue

            product = to_product(raw, "")
            idx = next((i for i, p in enumerate(catalog["products"])
                        if p["id"] == product["id"]), None)

            images_dir = CATALOG.parent / "images"

            if idx is not None:
                existing = catalog["products"][idx]
                existing.setdefault("stores", [])
                if not existing.get("image"):
                    images_dir.mkdir(exist_ok=True)
                    dest = images_dir / f"{product['id']}{img.suffix.lower()}"
                    dest.write_bytes(img.read_bytes())
                    existing["image"] = f"images/{dest.name}"
                merge_store(existing, ns.store, ns.url, offers)
                updated += 1
                print(f"  ✓ updated: {existing['name_en'] or existing['name_ar']} ({ns.store})")
            else:
                images_dir.mkdir(exist_ok=True)
                dest = images_dir / f"{product['id']}{img.suffix.lower()}"
                dest.write_bytes(img.read_bytes())
                product["image"] = f"images/{dest.name}"
                product["stores"] = []
                merge_store(product, ns.store, ns.url, offers)
                catalog["products"].append(product)
                added += 1
                print(f"  ✓ added:   {product['name_en'] or product['name_ar']} ({ns.store})")

            for o in offers:
                print(f"      [{o['kind']}] {o['ml']} ml = {o['price']} EGP")
        except Exception as e:
            failed += 1
            print(f"  ✗ failed: {e}")
        if not ns.local:
            time.sleep(2)  # stay within free-tier rate limit

    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDone. {added} added, {updated} updated, {failed} failed → {CATALOG}")
    print("Review with `git diff`, then commit & push to update the live site.")


if __name__ == "__main__":
    main()
