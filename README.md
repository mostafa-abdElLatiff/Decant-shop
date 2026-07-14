# Fragrance Wishlist — personal decant price-comparison catalogue

A zero-cost static site for tracking fragrances you want to try, where each
one can be sold by several different stores/sellers at different sizes and
prices. Browse, compare, pick specific store offers, and copy a plain-text
shopping list grouped by store — no checkout, no backend, no database
server. `products.json` in this repo *is* the database, and every commit
redeploys the site. Bilingual (English/Arabic) with a dark/light theme
toggle.

## Files

| File | What it is |
|---|---|
| `index.html` | The catalogue. Reads `products.json`. English by default, toggle to Arabic; dark by default, toggle to light. |
| `products.json` | Fragrances, their Fragrantica-style notes, what they're a dupe of (if any), and every store offering them. |
| `admin.html` | Manual fallback: add a fragrance or a new store offer from the browser. Commits directly to this repo via the GitHub API. |
| `extract.py` | Batch tool: feed it post images + a store name/link, Gemini (free tier) extracts the fragrance name, dupe info, notes, and sizes/prices, and merges the result in as an offer from that store. |
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
        { "kind": "leftover", "ml": 60, "price": 975 }
      ]
    }
  ]
}
```

A fragrance can have any number of `stores`, each with its own name/link and
its own list of `offers` (`kind` is `decant`, `full`, or `leftover`). If a
`dupe_of` name matches another product already in the catalogue (by
slugified name), the site cross-links them automatically — otherwise it's
just shown as plain text.

## Deploy (once, ~5 minutes)

1. Create a **public** GitHub repo (e.g. `decant-shop`) and push these files.
2. Repo → **Settings → Pages** → Source: *Deploy from a branch* → branch `main`, folder `/ (root)` → Save.
3. Your catalogue is live at `https://<username>.github.io/decant-shop/`
   and the admin panel at `.../admin.html`.

Every push to `main` rebuilds the site automatically (≈1 minute).

## Workflow A — batch extraction from post images (recommended)

```bash
pip install google-genai
export GEMINI_API_KEY="..."   # free key: https://aistudio.google.com/apikey
python extract.py --store "Ahmed Perfumes" --url "https://facebook.com/ahmedperfumes" posts/
git add -A && git commit -m "add offers from Ahmed Perfumes" && git push
```

Every extraction is tied to one store, since that's what a single batch of
post images usually represents. The script reads each image, extracts the
fragrance name (AR/EN), brand, what it's a dupe of, sizes/prices in EGP, and
Fragrantica-style notes, copies the image into `images/` the first time a
fragrance is added, and merges the result into `products.json`. If the
fragrance already exists (matched by slugified name), the given store's
offers are added or updated in place rather than creating a duplicate
product. Always review `git diff` before pushing — vision extraction is very
good but not infallible on prices.

Ollama (`--local`) is also supported for fully offline extraction, but can be
very slow depending on hardware — Gemini is the recommended path.

## Workflow B — add a fragrance/offer from the browser

1. Open `admin.html` on the live site.
2. One-time setup: enter GitHub username, repo name, branch, and a
   **fine-grained personal access token** scoped to this repo only with
   *Contents: Read and write* permission
   (GitHub → Settings → Developer settings → Fine-grained tokens).
   The token is stored only in your own browser (localStorage).
3. Fill the form: names, brand, dupe-of, notes, optional photo, then one
   store's name/link and its sizes/prices → **نشر على الموقع**. The page
   commits the image and the updated `products.json`; the site refreshes
   itself within a minute.
4. Re-submitting the same fragrance name with a different store name adds
   that store's offers alongside the existing ones, rather than replacing
   the fragrance.

## Security notes

- The token never leaves your browser except to `api.github.com`.
- Scope it to the single repo, Contents permission only, and set an expiry.
- `admin.html` is publicly *viewable*, but useless without a token.

## Costs

GitHub Pages: free. Gemini extraction: free tier. Domain: optional
(`github.io` subdomain is free). Total: **0 EGP/month**.
