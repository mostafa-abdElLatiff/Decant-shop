#!/usr/bin/env python3
"""
extract.py — turn perfume post images into wishlist entries.

You run this by hand whenever a seller posts something new — no AI agent
needed, this is a plain CLI. Every run is tied to one store (where you saw
the offer), so pass --store and --url alongside the image(s):

    # --- Claude (cloud, default — paid API, no free-tier quota wall) ---
    pip install anthropic
    export ANTHROPIC_API_KEY="..."     # https://console.anthropic.com/settings/keys
    python extract.py --store "Ahmed Perfumes" --url "https://facebook.com/ahmedperfumes" image.jpg
    python extract.py --store "Ahmed Perfumes" --url "https://facebook.com/ahmedperfumes" posts/

    # --- Gemini (cloud, free tier — has daily quota limits) ---
    pip install google-genai
    export GEMINI_API_KEY="..."        # free key from https://aistudio.google.com/apikey
    python extract.py --gemini --store "..." --url "..." image.jpg

    # --- Ollama (local, offline, no limits — can be slow depending on hardware) ---
    brew install ollama
    ollama pull llama3.2-vision        # one-time ~8 GB download
    python extract.py --local --store "..." --url "..." image.jpg

    # Facebook post URL (downloads ALL images automatically via gallery-dl):
    python extract.py --store "..." --url "..." "https://www.facebook.com/groups/.../posts/..."

    # Facebook CDN URLs (right-click image → Copy Image Address):
    python extract.py --store "..." --url "..." "https://scontent-*.fbcdn.net/..."

    # Seller posts local-brand bottles "inspired by" a named designer/niche
    # fragrance (a price banner names the reference, a separate photo shows
    # the actual bottle for sale) — pass --dupe-pattern so the reference name
    # goes to dupe_of instead of being mistaken for the product itself:
    python extract.py --dupe-pattern --store "..." --url "..." "https://www.facebook.com/..."

    # Seller writes each photo's fragrance name in the post text/caption
    # itself (visible per-photo on Facebook, e.g. multi-photo posts where
    # each image has its own caption) while sizes/prices are only in the
    # image — pass --use-captions so the caption is trusted for the name
    # instead of guessed from the image, which only has to supply
    # brand/notes/sizes/prices:
    python extract.py --use-captions --store "..." --url "..." "https://www.facebook.com/..."

For each image, extracts the fragrance name, brand, what it's a dupe of (if
stated), Fragrantica-style notes, and sizes/prices — then merges it into
products.json as an offer under the given store. Matching against existing
products first tries the slugified name, then falls back to a fuzzy
name+brand match so near-duplicate spellings/brand-suffix differences don't
create a second entry for the same fragrance.

Progress is saved after every image and cached in .extract_cache.json (per
store), so if the free-tier daily quota runs out mid-run, just re-run the
same command tomorrow — already-processed images are skipped automatically.

On success, changes are committed locally (never pushed) so there's a
history to review. Run `git log` / `git diff` and `git push` yourself when
you're happy with what landed.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.request
import tempfile
from pathlib import Path

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2-vision")
OLLAMA_URL   = "http://localhost:11434/api/generate"

try:
    import anthropic
except ImportError:
    anthropic = None

CATALOG = Path(__file__).parent / "products.json"
GEMINI_MODEL = "gemini-2.0-flash-lite"  # highest free-tier quota
CLAUDE_MODEL = "claude-opus-4-8"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
VALID_KINDS = {"decant", "full", "leftover"}
AS_SHOWN = "as-shown"

# Colors as used on Fragrantica's own "main accords" bars (scraped from live
# perfume pages — these are a fixed palette keyed by accord name, not chosen
# per-fragrance). Keep in sync with the ACCORD_COLORS object in index.html
# and admin.html.
ACCORD_COLORS = {
    "woody": "#774414", "amber": "#bc4d10", "warm spicy": "#CC3300",
    "metallic": "#97B0B7", "fresh spicy": "#83C928", "aromatic": "#37a089",
    "white floral": "#edf2fb", "animalic": "#8E4B13", "fresh": "#9be5ed",
    "vanilla": "#FFFEC0", "coffee": "#503B1D", "sweet": "#ee363b",
    "soft spicy": "#E27752", "fruity": "#FC4B29", "balsamic": "#ad8359",
    "powdery": "#EEDDCC", "aldehydic": "#d8e9f6", "iris": "#b7a7d7",
    "musky": "#E7D8EA", "earthy": "#544838", "yellow floral": "#FFDC10",
    "citrus": "#F9FF52", "tobacco": "#ad7727", "cacao": "#9a3a0d",
    "patchouli": "#63652e", "rose": "#FE016B", "marine": "#0E529B",
    "floral": "#FF5F8D", "caramel": "#DDA356", "leather": "#78483A",
    "smoky": "#827487", "mossy": "#5B6B32", "green": "#0E8C1D",
    "honey": "#FAA907", "chocolate": "#603000", "lavender": "#9B7DB8",
    "oud": "#544136", "herbal": "#6CA47F", "conifer": "#1b422f",
    "nutty": "#C68E5A", "salty": "#B7D8DC",
}

# Specific ingredient/note names -> nearest Fragrantica accord family.
ACCORD_ALIASES = {
    "akigalawood": "woody", "aldehyde": "aldehydic", "almond": "nutty",
    "ambrofix": "amber", "ambroxan": "amber", "anise": "aromatic",
    "apple": "fruity", "aquatic": "marine", "aquatic notes": "marine",
    "bergamot": "citrus", "bitter": "earthy", "bitter orange": "citrus",
    "cardamom": "warm spicy", "cedarwood": "woody", "cinnamon": "warm spicy",
    "cocoa": "chocolate", "coconut": "fruity", "cognac": "balsamic",
    "cucumber": "green", "dragon fruit": "fruity", "fig": "green",
    "gazelle leather (tanned leather)": "leather", "geranium": "green",
    "ginger": "fresh spicy", "granny smith apple": "fruity",
    "grapefruit": "citrus",
    "green notes": "green", "juniper": "aromatic", "lactonic": "powdery",
    "mahonial": "woody", "mandarin": "citrus", "musk": "musky",
    "neroli": "white floral", "nutmeg": "warm spicy", "oakmoss": "mossy",
    "ozonic": "fresh", "peony": "floral", "red cranberry": "fruity",
    "refreshing nuance": "fresh", "resin (smoky)": "smoky", "rum": "balsamic",
    "sage": "herbal", "sandalwood": "woody", "sea salt": "salty",
    "sea water": "marine", "soft": "powdery", "soft spices": "soft spicy",
    "tangy": "citrus", "tea": "green", "terpenic": "aromatic",
    "toffee": "caramel", "tonka bean": "vanilla", "tonka beans": "vanilla",
    "tropical": "fruity", "vetiver": "earthy", "violet": "powdery",
    "virginia cedarwood": "woody", "walnut flavor": "nutty",
    "white flowers": "white floral", "white musk": "musky",
    "yellow flowers": "yellow floral", "yuzu": "citrus",
}

FALLBACK_COLOR = "#9C9C9C"


def accord_color(label: str) -> str:
    key = (label or "").strip().lower()
    if key in ACCORD_COLORS:
        return ACCORD_COLORS[key]
    if key in ACCORD_ALIASES:
        return ACCORD_COLORS[ACCORD_ALIASES[key]]
    for name, color in ACCORD_COLORS.items():
        if name in key or key in name:
            return color
    return FALLBACK_COLOR

PROMPT_CONTEXT_DEFAULT = """You are extracting a perfume listing from a social media post image
for a perfume decant catalogue. The image usually contains the fragrance name
(often in both English and Arabic), size/price lines like "10 ml = 220"
(prices in EGP), sometimes colored accord bars with note labels, and
sometimes a mention of which original/designer fragrance this one is a dupe
of ("انسباير من", "دوب لـ", "inspired by", etc). Most listings are the
genuine named fragrance being sold directly — only fill "dupe_of" if the
image explicitly says this is inspired by / a clone of a different named
fragrance."""

PROMPT_CONTEXT_DUPE_PATTERN = """You are extracting a perfume listing from a social media post image
for a perfume decant catalogue. This seller's posts follow a two-panel
template:
- LEFT panel: a price banner ("10 ml = 220" etc, in EGP) plus a fragrance
  NAME/BRAND text block (English + Arabic) and a colored notes/accord list,
  sometimes with a small stock-photo thumbnail. This LEFT-panel name is the
  REFERENCE / ORIGINAL / "inspired by" fragrance — it is NOT the product
  being sold. It goes in "dupe_of", formatted "Name — Brand".
- RIGHT panel: a real photograph (hand holding a bottle, or a shelf) of the
  ACTUAL bottle being sold. This bottle has its own printed name/logo, often
  a DIFFERENT local/Middle-Eastern brand (Lattafa, Armaf, Rasasi, Khadlaj,
  Afnan, French Avenue, Rayhaan, or similar) — read the RIGHT-panel bottle's
  own printed text to decide the product identity, never assume from the
  left banner alone. This is the ACTUAL PRODUCT — it goes in
  "name_en"/"name_ar"/"brand".

NEVER put the left-banner's famous designer/niche name into "name_en" —
always read the right-panel bottle photo's own printed text for
name_en/brand, and always put the left-banner name into dupe_of. If (rare)
the right-panel photo is genuinely a stock photo of the SAME bottle named on
the left (no different local bottle shown), then name_en = that fragrance
and dupe_of = [] — check carefully, this is the exception not the rule. If
two listings are stacked in one image with only one price banner, pick
whichever is most clearly associated with that banner/photo."""

PROMPT_SCHEMA = """
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
- "type": decant for ml-sized splits. "full" ONLY if the post explicitly
  states this is a new/sealed/complete bottle — do not assume "full" just
  because a box is shown or a nominal bottle capacity is printed on it.
  Otherwise, if the bottle is visibly opened/used or the post is about
  remaining/leftover stock (باقي/بواقي التقسيم, "remaining bottles"), use
  "leftover".
- For each size: if an exact or approximate remaining amount is stated
  (e.g. "10 ml", "~92 ml", "حوالي 46 ملي"), use that number for "ml". If the
  price has no quantity attached at all (e.g. just a price, or text like "as
  shown" / "كما بالصوره" / "Old batch"), set "ml" to the literal string
  "as-shown" instead of guessing a number from the box's printed capacity.
- Include every size/price pair you can read. Prices are integers in EGP.
- "dupe_of" only if the post explicitly says this is inspired by / a dupe of
  another named fragrance — do not guess.
- List notes top to bottom in order of prominence if accord bars are visible,
  else [].
- Do not invent data you cannot read from the image."""


PROMPT_KNOWN_NAME = """

The fragrance name for this image is already confirmed from the seller's
own Facebook caption for this photo: "{name}". Use exactly this text (only
fix an obvious typo, e.g. a missing letter) for "name_en" — do not guess a
different name from the image. Still read brand (from the bottle/box if
visible, or infer it from the name itself), dupe_of (only if explicitly
stated in the image), notes, and sizes/prices from the image as normal."""


def build_prompt(dupe_pattern: bool, known_name: str = None) -> str:
    context = PROMPT_CONTEXT_DUPE_PATTERN if dupe_pattern else PROMPT_CONTEXT_DEFAULT
    prompt = context + PROMPT_SCHEMA
    if known_name:
        prompt += PROMPT_KNOWN_NAME.format(name=known_name)
    return prompt


def slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s or f"p-{int(time.time())}"


def is_url(s: str) -> bool:
    return s.startswith("http://") or s.startswith("https://")


def is_facebook_url(s: str) -> bool:
    return "facebook.com" in s and ("/posts/" in s or "story_fbid" in s or "permalink" in s)


def download_facebook_post(url: str, write_metadata: bool = False) -> list:
    """Use gallery-dl to download all images from a Facebook post. Returns
    a list of (Path, caption_or_None) — caption is only populated when
    write_metadata is True and Facebook exposed a per-photo caption in the
    gallery-dl metadata sidecar."""
    if not shutil.which("gallery-dl"):
        sys.exit(
            "gallery-dl is required for Facebook URLs.\n"
            "Install it with:  brew install gallery-dl"
        )
    tmp_dir = Path(tempfile.mkdtemp())
    print(f"  fetching all images from Facebook post...")
    succeeded = False
    for browser in ("chrome", "firefox", "safari", "chromium", "edge"):
        cmd = ["gallery-dl", f"--cookies-from-browser={browser}", "--directory", str(tmp_dir)]
        if write_metadata:
            cmd.append("--write-metadata")
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True)
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

    results = []
    for img in images:
        caption = None
        if write_metadata:
            sidecar = img.with_suffix(img.suffix + ".json")
            if sidecar.exists():
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                    caption = (meta.get("caption") or "").strip() or None
                except (json.JSONDecodeError, OSError):
                    pass
        results.append((img, caption))
    return results


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


def collect_images(args, use_captions: bool = False):
    paths = []  # list of (Path, display_label_or_None, caption_or_None)
    for a in args:
        if is_facebook_url(a):
            print(f"→ Facebook post: {a}")
            paths += [(img, None, caption) for img, caption in download_facebook_post(a, write_metadata=use_captions)]
        elif is_url(a):
            print(f"→ image URL: {a[:80]}...")
            try:
                paths.append((download_url(a), None, None))
            except Exception as e:
                print(f"  ✗ could not download: {e}")
        else:
            p = Path(a)
            if p.is_dir():
                paths += [(f, f, None) for f in sorted(p.iterdir()) if f.suffix.lower() in IMAGE_EXTS]
            elif p.suffix.lower() in IMAGE_EXTS:
                paths.append((p, p, None))
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
            "color": accord_color(n.get("label_en") or n.get("label_ar") or ""),
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
    offers = []
    for s in raw.get("sizes", []):
        if not s.get("price"):
            continue
        ml = s.get("ml")
        if ml == AS_SHOWN or (isinstance(ml, str) and ml.strip().lower() in ("as shown", "as-shown")):
            offers.append({"kind": kind, "ml": AS_SHOWN, "price": int(s["price"])})
        elif ml:
            offers.append({"kind": kind, "ml": int(ml), "price": int(s["price"])})
    return sorted(offers, key=lambda s: (s["ml"] == AS_SHOWN, s["ml"] if s["ml"] != AS_SHOWN else 0))


STOPWORDS = {"perfumes", "perfume", "men", "women", "fragrances", "fragrance"}


def _tokens(text: str) -> set:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return set(re.sub(r"[^a-z0-9]+", " ", text.lower()).split()) - STOPWORDS


def find_existing_product(catalog: dict, name_en: str):
    """Exact slug match first, then a *conservative* fuzzy match: only when
    the normalized core-name token sets are exactly equal (catches accent/
    punctuation spelling differences like "Édition" vs "Edition"). Deliberately
    NOT a subset/containment match — that would also match "Club De Nuit Man"
    against "Club De Nuit Intense Man", which are different real fragrances.
    A missed duplicate (occasional near-duplicate entry) is a far cheaper
    mistake than silently merging two different products' offers together,
    which is why this stays strict for an unattended run."""
    exact_id = slugify(name_en)
    for p in catalog["products"]:
        if p["id"] == exact_id:
            return p

    core = _tokens(name_en)
    if len(core) < 2:
        return None
    for p in catalog["products"]:
        if _tokens(p["name_en"]) == core:
            return p
    return None


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


class QuotaExhausted(Exception):
    """Daily free-tier quota hit — caller should save progress and stop,
    not lose everything processed so far in this run."""


def gemini_generate(client, img_path: Path, prompt: str) -> str:
    uploaded = client.files.upload(file=img_path)
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=GEMINI_MODEL, contents=[prompt, uploaded])
            return resp.text
        except Exception as ex:
            err = str(ex)
            if "429" not in err:
                raise
            if "PerDay" in err or "per_day" in err.lower():
                raise QuotaExhausted(
                    "Daily free-tier quota exhausted.\n"
                    "  Options:\n"
                    "  1. Wait until tomorrow (UTC midnight) for quota to reset — just\n"
                    "     re-run the same command, already-processed images are skipped.\n"
                    "  2. Enable billing at https://console.cloud.google.com/billing\n"
                    "     (costs ~$0.01 per 100 images — essentially free).\n"
                    "  3. Run with --local to use Ollama offline (no limits, but can be\n"
                    "     very slow on modest hardware)."
                ) from None
            if attempt < 2:
                wait = (attempt + 1) * 10
                print(f"  ⏳ rate limit — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


IMAGE_MEDIA_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".webp": "image/webp",
}


def claude_generate(client, img_path: Path, prompt: str) -> str:
    import base64
    media_type = IMAGE_MEDIA_TYPES.get(img_path.suffix.lower(), "image/jpeg")
    img_b64 = base64.standard_b64encode(img_path.read_bytes()).decode("utf-8")
    for attempt in range(3):
        try:
            resp = client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=2048,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {"type": "base64", "media_type": media_type, "data": img_b64},
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
            return next(b.text for b in resp.content if b.type == "text")
        except anthropic.RateLimitError:
            if attempt < 2:
                wait = (attempt + 1) * 10
                print(f"  ⏳ rate limit — waiting {wait}s...")
                time.sleep(wait)
            else:
                raise


def ollama_generate(img_path: Path, prompt: str) -> str:
    import base64
    img_b64 = base64.b64encode(img_path.read_bytes()).decode()
    body = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
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


CACHE_FILE = Path(__file__).parent / ".extract_cache.json"


def load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict):
    CACHE_FILE.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def save_catalog(catalog: dict):
    CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8")


def git_commit_local(message: str):
    """Stage products.json/images and commit locally. Never pushes —
    review with `git log`/`git diff` and push yourself when ready."""
    repo = CATALOG.parent
    status = subprocess.run(
        ["git", "status", "--porcelain", "products.json", "images/"],
        cwd=repo, capture_output=True, text=True,
    )
    if not status.stdout.strip():
        return False
    subprocess.run(["git", "add", "products.json", "images/"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True)
    return True


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--local", action="store_true")
    parser.add_argument("--gemini", action="store_true",
                         help="Use Gemini (free tier, daily quota limits) instead of the "
                              "default Claude backend.")
    parser.add_argument("--dupe-pattern", action="store_true",
                         help="This seller's posts show a reference/designer fragrance "
                              "alongside a different actual local-brand bottle for sale "
                              "(see module docstring). Omit for sellers who sell the named "
                              "fragrance directly.")
    parser.add_argument("--use-captions", action="store_true",
                         help="This seller writes each photo's fragrance name in the post's "
                              "own per-photo caption on Facebook — trust that for the name "
                              "instead of guessing it from the image (see module docstring).")
    parser.add_argument("--store", required=True, help="Name of the store/seller this offer is from")
    parser.add_argument("--url", default="", help="Link to the store/seller (website or Facebook profile)")
    parser.add_argument("sources", nargs="+", help="Image file(s), folder(s), or Facebook/image URL(s)")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    ns = parser.parse_args()
    base_prompt = build_prompt(ns.dupe_pattern)

    client = None
    if ns.local:
        print(f"  using local model: {OLLAMA_MODEL}  (ollama)")
    elif ns.gemini:
        try:
            from google import genai
        except ImportError:
            sys.exit("Missing package. Run:  pip install google-genai")
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            sys.exit("Set GEMINI_API_KEY  or drop --gemini to use the default Claude backend.")
        client = genai.Client(api_key=api_key)
        print(f"  using model: {GEMINI_MODEL}  (gemini)")
    else:
        if anthropic is None:
            sys.exit("Missing package. Run:  pip install anthropic")
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            sys.exit(
                "Set ANTHROPIC_API_KEY (https://console.anthropic.com/settings/keys)\n"
                "  or use --gemini / --local for the other backends."
            )
        client = anthropic.Anthropic(api_key=api_key)
        print(f"  using model: {CLAUDE_MODEL}  (claude)")

    images = collect_images(ns.sources, use_captions=ns.use_captions)
    if not images:
        sys.exit("No images found.")

    catalog = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.exists() \
        else {"settings": {}, "products": []}
    cache = load_cache()
    done = set(cache.get(ns.store, []))

    added, updated, failed, cached_skipped = 0, 0, 0, 0
    images_dir = CATALOG.parent / "images"
    quota_hit = False

    for img, original, caption in images:
        label = original.name if original else img.name
        if label in done:
            cached_skipped += 1
            continue
        print(f"→ {label}" + (f"  (caption: {caption!r})" if caption else ""))
        prompt = build_prompt(ns.dupe_pattern, known_name=caption) if caption else base_prompt
        try:
            if ns.local:
                text = ollama_generate(img, prompt)
            elif ns.gemini:
                text = gemini_generate(client, img, prompt)
            else:
                text = claude_generate(client, img, prompt)
            raw = parse_json(text)

            offers = to_offers(raw)
            if not offers:
                print("  ⚠ no sizes/prices found — skipped (check the image)")
                failed += 1
                continue

            name_en = raw.get("name_en") or raw.get("name_ar") or ""
            product = to_product(raw, "")
            existing = find_existing_product(catalog, name_en)

            if existing is not None:
                existing.setdefault("stores", [])
                if not existing.get("image"):
                    images_dir.mkdir(exist_ok=True)
                    dest = images_dir / f"{existing['id']}{img.suffix.lower()}"
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

            done.add(label)
        except QuotaExhausted as e:
            print(f"\n✗ {e}")
            quota_hit = True
        except Exception as e:
            failed += 1
            print(f"  ✗ failed: {e}")
        finally:
            # save after every image so a quota cutoff or crash never loses progress
            save_catalog(catalog)
            cache[ns.store] = sorted(done)
            save_cache(cache)
        if quota_hit:
            break
        if ns.gemini:
            time.sleep(2)  # stay within Gemini's free-tier rate limit

    print(f"\nDone. {added} added, {updated} updated, {failed} failed, "
          f"{cached_skipped} already-processed skipped → {CATALOG}")

    committed = git_commit_local(
        f"extract.py: {ns.store} — {added} added, {updated} updated"
    )
    if committed:
        print("Committed locally (not pushed). Review with `git log`/`git diff`, then `git push` when ready.")
    else:
        print("No catalog changes to commit.")


if __name__ == "__main__":
    main()
