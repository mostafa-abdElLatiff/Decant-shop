# pending_facebook/

Staging area for images fetched from a Facebook group post via
`.github/workflows/fetch-facebook-post.yml` (triggered from `trigger.html`
or the Actions tab — see the README's "Workflow D" section).

Each run creates its own subfolder here: `<store-slug>-<timestamp>/`,
containing the downloaded photos, a `<photo>.json` sidecar per photo with
Facebook's own caption text for it (some sellers write prices/sizes in
the post's caption rather than on a price card in the photo — check
these if a photo alone doesn't show a price), and a `meta.json`
(`store_name`, `post_url`, `fetched_at`).

**This is a staging area only — nothing here has been read or added to
`products.json` yet.** No AI processing happens automatically (that step
costs money and is deliberately kept manual/free — see the README).

## Processing a batch

Open a Claude Code session and ask it to process a folder here, or run
`extract.py` directly against it — it already accepts a local directory
of images:

```
python extract.py --store "<store name>" --url "<store url>" pending_facebook/<folder>/
```

Add `--dupe-pattern` if these are "dupe/inspired-by" style posts (a
famous perfume's name/photo alongside the actual bottle being sold —
see `extract.py`'s own `--help` for details).

Once a batch is merged into `products.json`, delete its subfolder
(`git rm -r pending_facebook/<folder>`) in the same commit — this
directory should only ever contain *unprocessed* batches.
