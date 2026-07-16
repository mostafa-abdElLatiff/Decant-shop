# Fragrance Wishlist — personal decant price-comparison catalogue

A zero-cost static site for tracking fragrances you want to try, where each
one can be sold by several different stores/sellers at different sizes and
prices. Browse, filter by type/store, search, compare, get a simple
"cheaper elsewhere" nudge in the cart, and copy a plain-text shopping list
grouped by store — no checkout, no backend, no database server.
`products.json` in this repo *is* the database, and every push redeploys the
site. Bilingual (English/Arabic) with a dark/light theme toggle. Prices
shown never include shipping — each store charges its own, so the site
carries a disclaimer to that effect.

## Stores — how to update each one

Every store that feeds this catalogue has its own script with the exact
command to run. None of them need me (an AI agent) to run — they're plain
CLI tools you trigger yourself whenever a seller posts something new or you
just want a refresh. None of them push to GitHub either — they only commit
locally, so you always review before `git push`.

| Store | Type | Script |
|---|---|---|
| EsLam Nasser | Facebook seller | `python update_eslam_nasser.py "<post URL>"` |
| Mostafa Mohamed | Facebook seller | `python update_mostafa_mohamed.py "<post URL>"` |
| roseperfume.online | Shopify | `python sync_roseperfume.py` (no URL needed, re-polls the whole collection) |
| sniffz-eg.com | Shopify | `python sync_sniffz.py` (no URL needed) |
| MO Shawky | Odoo storefront | `python sync_mo_shawky.py` (no URL needed) |

**Adding a brand-new store later:** see Workflows A/C below for a Facebook
seller vs. a store with its own website — both have a copyable starting
point so you're not building from scratch.

## Files

| File | What it is |
|---|---|
| `index.html` | The catalogue. Filter by decant/full/leftover and by store, search (🔍 icon in the header opens it from anywhere on the page without scrolling up), click a fragrance's photo to zoom, cart shows a thumbnail + a "better value elsewhere" tip per line when one exists. |
| `products.json` | Fragrances, their Fragrantica-style notes, what they're a dupe of (if any), and every store offering them. |
| `admin.html` | Manual editor: add a fragrance, add/update a store's offers, or **edit an existing fragrance's name/brand/notes in place** (search the product list at the bottom, click تعديل/Edit). Commits directly to this repo via the GitHub API. |
| `extract.py` | The underlying batch tool for *any* Facebook seller's post — the two `update_*.py` scripts below are just this pre-filled with a store's name/link. Claude (default) reads each post image and extracts name, dupe info, notes, and sizes/prices; `--gemini` or `--local` (Ollama) are available as alternate backends. |
| `update_eslam_nasser.py`, `update_mostafa_mohamed.py` | One-line wrappers around `extract.py` for these two Facebook sellers — just pass a post URL. |
| `sync_roseperfume.py`, `sync_sniffz.py` | Fully automatic, no-AI sync for these two Shopify stores — re-polls their product API and updates offers. |
| `sync_mo_shawky.py` | Fully automatic, no-AI sync for MO Shawky's Odoo storefront — Odoo doesn't expose a JSON API like Shopify does, so this parses the product grid HTML directly. |
| `brand_prefixes.py` | Shared "Brand Fragrance Name" recognition table used by `sync_mo_shawky.py` and `sync_sniffz.py` (stores whose listings don't have a separate structured brand field). |
| `rp_notes.py` | Arabic→English note-name translation table used by `sync_roseperfume.py`. |
| `find_duplicates.py` | Read-only report of likely duplicate products worth merging by hand — run occasionally (see Maintenance below). |
| `images/` | Fragrance photos referenced by the catalogue. |

## Data model

Each product looks like:

```jsonc
{
  "id": "french-avenue-jasmere",
  "name_en": "French Avenue Jasmere Parfum",
  "name_ar": "جاسمير — فرينش أفينيو",
  "brand": "French Avenue",
  "dupe_of": ["Tilia — Marc-Antoine Barrois"],
  "image": "images/french-avenue-jasmere.jpg",
  "accords": [{ "label_en": "Yellow Flowers", "label_ar": "زهور صفراء", "color": "#F5F0A9", "w": 100 }],
  "stores": [
    {
      "name": "Ahmed Perfumes",
      "url": "https://facebook.com/ahmedperfumes",
      "product_url": "https://www.facebook.com/groups/.../posts/...",
      "image": "images/french-avenue-jasmere--ahmed-perfumes.jpg",
      "offers": [
        { "kind": "decant", "ml": 5, "price": 450, "first_seen": "2026-07-01" },
        { "kind": "full", "ml": 100, "price": 4400, "first_seen": "2026-06-10", "prev_price": 4800 },
        { "kind": "leftover", "ml": 60, "price": 975, "first_seen": "2026-05-20" },
        { "kind": "leftover", "ml": "as-shown", "price": 700, "first_seen": "2026-05-20" }
      ]
    }
  ]
}
```

A fragrance can have any number of `stores`, each with its own name/link and
its own list of `offers` (`kind` is `decant`, `full`, or `leftover`). `ml` is
normally a number, but for a `leftover` bottle where the seller didn't state
how much is left, it's the literal string `"as-shown"` instead of a guessed
number — the site renders that as "as shown" / "كما بالصورة" rather than a
fake quantity. Only mark an offer `"full"` when it's explicitly a new/sealed
bottle — a box being visible, or a nominal capacity being printed on it, is
*not* enough evidence on its own. If a `dupe_of` name matches another
product already in the catalogue (by slugified name), the site cross-links
them automatically — otherwise it's just shown as plain text.

Each offer also carries `first_seen` (the date it was first added for that
store, stamped automatically by `extract.py`/`sync_*.py`/`admin.html` —
never hand-edit it) and, only while relevant, `prev_price` (the price it
just dropped from). The site uses these for two small badges: a "New" tag
on offers first seen in the last 14 days, and a struck-through old price
next to the current one when it just dropped. `prev_price` clears itself
automatically the next time the price rises back or changes again — there's
nothing to maintain by hand.

Each store entry can also carry `product_url` (the specific product page or
Facebook post this listing came from — different from `url`, which is the
store's general homepage/profile) and `image` (that specific store's own
photo of this listing, shown as a small thumbnail next to the store's
offers). Both are optional and only appear once a store has been synced
since this feature was added. `store.image` is refreshed on every sync/
extraction run (unlike the product-level `image`, which is a stable hero
photo set once and left alone) specifically so a "leftover — as shown"
offer always shows the bottle it was actually photographed with, never a
different store's picture of the same fragrance.

### Matching — how a scraped/extracted item finds its product

`find_existing_product()` (in `extract.py`, shared by every `sync_*.py`
script and mirrored in `admin.html`) decides whether a new listing is the
*same* fragrance as an existing product or a *different* one. It requires
both the name **and the brand** to be compatible — matching on name text
alone let two different fragrances that happen to share a generic name
(e.g. "Khanjar" sold by both Omanluxury and Lattafa, or "Private" by
Mercedes-Benz vs. by Najla Abdul Samad Al Qurashi) silently collapse into
one product with the wrong brand and a mix of both sellers' offers. Brand
matching is deliberately lenient about sub-brand/rebrand/spelling
differences ("Armani" vs "Emporio Armani", "Maison Martin Margiela" vs
"Maison Margiela") so those don't get wrongly split into duplicates — see
`_brands_match()`'s docstring in `extract.py` for the exact rule. When a
new product's plain name-slug is already taken by a different, brand-
incompatible product, `unique_id_for()` disambiguates the id with a brand
suffix (e.g. `khanjar-lattafa`) instead of colliding two different
fragrances onto the same id.

Accord/note colors come from a fixed table (`ACCORD_COLORS` in `extract.py`,
mirrored in `admin.html`) matching Fragrantica's own "main accords" bar
colors — the same note always gets the same color across every fragrance.
Adding a new note name to that table (once) is all that's needed for it to
color correctly everywhere going forward.

## Deploy (once, ~5 minutes)

1. Create a **public** GitHub repo (e.g. `decant-shop`) and push these files.
2. Repo → **Settings → Pages** → Source: *Deploy from a branch* → branch `main`, folder `/ (root)` → Save.
3. Your catalogue is live at `https://<username>.github.io/decant-shop/`
   and the admin panel at `.../admin.html`.

Every push to `main` rebuilds the site automatically (≈1 minute). None of
the tools below push for you — they only commit locally — so you're always
the one who decides what goes live and `git push` is always your own last
step.

## Workflow A — a Facebook seller's post

For EsLam Nasser or Mostafa Mohamed, just run their `update_*.py` script
(see the Stores table above) with the post URL. For a **new** Facebook
seller:

```bash
pip install anthropic
export ANTHROPIC_API_KEY="..."   # https://console.anthropic.com/settings/keys
python extract.py --store "Ahmed Perfumes" --url "https://facebook.com/ahmedperfumes" \
  "https://www.facebook.com/groups/.../posts/..."
```

Every extraction is tied to one store, since that's what a single batch of
post images usually represents. The script downloads every image in the
post, reads each one, extracts the fragrance name (AR/EN), brand, what it's
a dupe of, sizes/prices in EGP, and Fragrantica-style notes, copies the
image into `images/` the first time a fragrance is added, and merges the
result into `products.json`.

Some sellers post local-brand bottles "inspired by" a named designer/niche
fragrance — a price banner names the reference fragrance, while a *separate*
photo shows the actual bottle for sale. For those sellers, add
`--dupe-pattern` so the reference name goes into `dupe_of` instead of being
mistaken for the product itself (this is what `update_eslam_nasser.py`
does under the hood). Omit the flag for sellers who just sell the named
fragrance directly, like `update_mostafa_mohamed.py` does — most sellers are
this simpler case. Once you've settled on the flag for a new seller, copy
one of the two `update_*.py` scripts as a starting point so you don't have
to remember it next time.

Progress saves after every single image (into `products.json` and a local
`.extract_cache.json`), so if the run is interrupted — or, with `--gemini`,
the free-tier daily quota runs out — nothing is lost: just re-run the exact
same command and already-processed images are skipped automatically. On
success the script commits locally (never pushes) so there's a clean
history to review with `git diff` / `git log` before you `git push`
yourself.

Ollama (`--local`) is also supported for fully offline extraction, but can be
very slow depending on hardware — Gemini is the recommended path.

## Workflow B — add or edit a fragrance from the browser

1. Open `admin.html` on the live site.
2. One-time setup: enter GitHub username, repo name, branch, and a
   **fine-grained personal access token** scoped to this repo only with
   *Contents: Read and write* permission
   (GitHub → Settings → Developer settings → Fine-grained tokens).
   The token is stored only in your own browser (localStorage).
3. **To add a fragrance or a store's offers**: fill the form — names, brand,
   dupe-of, notes, optional photo, then one store's name/link and its
   sizes/prices → **نشر على الموقع**. Re-submitting the same fragrance name
   with a different store name adds that store's offers alongside the
   existing ones rather than replacing the fragrance.
4. **To fix a name, brand, dupe-of, or notes that came out wrong**: scroll to
   "المنتجات الحالية" at the bottom, search for the fragrance, click
   **تعديل** (Edit). The form fills in with its current data — edit whatever
   field is wrong and leave the store/offers section empty (it's optional
   while editing) to update *only* the fragrance's own details without
   touching any store's pricing. Publish as usual.

## Workflow C — a store that runs its own website

Three examples to copy from, depending on the platform:

- **Shopify** (`sync_roseperfume.py`, `sync_sniffz.py`): Shopify exposes a
  public JSON product API (`/products.json` on any collection), so it's
  plain structured-data parsing — title, vendor/tags, variant prices/stock,
  and the description text for notes and dupe references. No AI/vision
  needed. Copy one of these two scripts, change `STORE_NAME`/`STORE_URL`/the
  collection URL(s), and adjust the description-parsing regexes to match the
  new store's write-up style (Arabic vs English, "dupe of X" phrasing, etc).
- **Odoo** (`sync_mo_shawky.py`): Odoo doesn't have a public JSON API, so
  this scrapes the rendered product grid HTML directly with regex — still no
  AI/vision, just a different data source. Useful as a starting point for
  any other server-rendered (non-Shopify) storefront.
- **A Facebook seller instead of a website**: that's Workflow A, no new code
  needed.

Run any of them with `python sync_<store>.py`:

```bash
python sync_roseperfume.py
```

All three only ever add or update products they can positively re-identify
(exact ID or exact normalized-name match) — they never remove a listing they
can't confidently re-match, since a wrong auto-removal (stripping a store
from the wrong product) is worse than an occasional stale/duplicate entry.
They also all check availability/stock before including an offer — an item
with nothing currently purchasable is skipped rather than added with a
guess. They commit locally, never push.

## Maintenance — catching duplicates

`extract.py` and every `sync_*.py` script merge conservatively on purpose:
they only auto-match a product by exact ID or exact normalized name, never a
fuzzy/subset match, because a wrong auto-merge (mixing two different
fragrances' pricing together) is a much worse mistake than an occasional
near-duplicate entry (e.g. "Jasmere Parfum" vs "French Avenue Jasmere
Parfum" — same fragrance, different spelling; this happens most often when
a seller's own naming differs slightly from how the fragrance is already in
the catalogue from another store). Run this occasionally to see what's worth
merging by hand via `admin.html`'s Edit, or a quick manual `products.json`
edit:

```bash
python find_duplicates.py
```

It only prints candidates — it never changes anything itself.

## Security notes

- The token never leaves your browser except to `api.github.com`.
- Scope it to the single repo, Contents permission only, and set an expiry.
- `admin.html` is publicly *viewable*, but useless without a token.

## Costs

GitHub Pages: free. Claude extraction: pay-as-you-go, a few cents per batch
of images (use `--gemini` for the free-tier alternative, with daily quota
limits). Domain: optional (`github.io` subdomain is free).
