# Fragrance Wishlist — personal decant price-comparison catalogue

A zero-cost static site for tracking fragrances you want to try, where each
one can be sold by several different stores/sellers at different sizes and
prices. Browse, filter by type/store, search, compare, pick specific store
offers, and copy a plain-text shopping list grouped by store — no checkout,
no backend, no database server. `products.json` in this repo *is* the
database, and every push redeploys the site. Bilingual (English/Arabic) with
a dark/light theme toggle.

## Files

| File | What it is |
|---|---|
| `index.html` | The catalogue. Reads `products.json`. Filter by decant/full/leftover and by store, search (🔍 icon in the header opens it from anywhere on the page), click a fragrance's photo to zoom, cart shows a thumbnail per line. |
| `products.json` | Fragrances, their Fragrantica-style notes, what they're a dupe of (if any), and every store offering them. |
| `admin.html` | Manual editor: add a fragrance, add/update a store's offers, or **edit an existing fragrance's name/brand/notes in place** (search the product list at the bottom, click تعديل/Edit). Commits directly to this repo via the GitHub API. |
| `extract.py` | Batch tool for a Facebook seller's post: feed it post images + a store name/link, Gemini (free tier) extracts the fragrance name, dupe info, notes, and sizes/prices, and merges the result in as an offer from that store. |
| `sync_roseperfume.py` | Fully automatic, no-AI sync for roseperfume.online (a Shopify store) — re-polls their product API and updates offers. Run it yourself whenever you want (see Workflow C); nothing on this machine runs it on a timer. |
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
      "offers": [
        { "kind": "decant", "ml": 5, "price": 450 },
        { "kind": "full", "ml": 100, "price": 4400 },
        { "kind": "leftover", "ml": 60, "price": 975 },
        { "kind": "leftover", "ml": "as-shown", "price": 700 }
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

## Workflow A — batch extraction from a Facebook seller's post

```bash
pip install google-genai
export GEMINI_API_KEY="..."   # free key: https://aistudio.google.com/apikey
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
mistaken for the product itself:

```bash
python extract.py --dupe-pattern --store "EsLam Nasser" --url "..." "https://www.facebook.com/..."
```

Omit the flag for sellers who just sell the named fragrance directly (decant
or full bottle of the real thing) — most sellers are this simpler case.

Progress saves after every single image (into `products.json` and a local
`.extract_cache.json`), so if the free-tier daily quota runs out partway
through, nothing is lost — just re-run the exact same command tomorrow and
already-processed images are skipped automatically. On success the script
commits locally (never pushes) so there's a clean history to review with
`git diff` / `git log` before you `git push` yourself.

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

## Workflow C — sync a store that runs its own website (Shopify etc.)

`sync_roseperfume.py` is the reference example: roseperfume.online runs on
Shopify, which exposes a public JSON product API (`/products.json`), so no
AI/vision is needed at all — it's plain structured-data parsing (title,
tags, variant prices/stock, and the description text for dupe references and
notes). Run it whenever you want to refresh that store's listings:

```bash
python sync_roseperfume.py
```

It only ever adds or updates products it can positively re-identify (exact
ID or exact normalized-name match) — it never removes a listing it can't
confidently re-match, since a wrong auto-removal (stripping a store from the
wrong product) is worse than an occasional stale/duplicate entry. It commits
locally, never pushes.

**To add a similar store in the future**: if it also runs on Shopify, copy
`sync_roseperfume.py` as a starting point and change `COLLECTION_URL`,
`STORE_NAME`, `STORE_URL`, and the non-fragrance keyword/parsing rules to
match the new store's product page structure — most Shopify stores share the
same `/products.json` shape. If it's a Facebook seller instead, Workflow A
already covers that with no new code needed.

## Maintenance — catching duplicates

Both `extract.py` and `sync_roseperfume.py` merge conservatively on purpose:
they only auto-match a product by exact ID or exact normalized name, never a
fuzzy/subset match, because a wrong auto-merge (mixing two different
fragrances' pricing together) is a much worse mistake than an occasional
near-duplicate entry (e.g. "Jasmere Parfum" vs "French Avenue Jasmere
Parfum" — same fragrance, different spelling). Run this occasionally to see
what's worth merging by hand via `admin.html`'s Edit, or a quick manual
`products.json` edit:

```bash
python find_duplicates.py
```

It only prints candidates — it never changes anything itself.

## Security notes

- The token never leaves your browser except to `api.github.com`.
- Scope it to the single repo, Contents permission only, and set an expiry.
- `admin.html` is publicly *viewable*, but useless without a token.

## Costs

GitHub Pages: free. Gemini extraction: free tier. Domain: optional
(`github.io` subdomain is free). Total: **0 EGP/month**.
