#!/usr/bin/env python3
"""
update_eslam_nasser.py — add EsLam Nasser's latest Facebook post to the catalogue.

EsLam Nasser posts decant bottles labeled with a named designer/niche
fragrance's own name/brand -- but he's confirmed to sell ONLY dupes/
clones, never the genuine article (his prices run 100-270 EGP for
3-10ml where every other store's genuine listing of the exact same name
runs 800-8500+ EGP). This always runs extract.py with both
--dupe-pattern AND --always-dupe, so the reference name always lands in
dupe_of (never taken as the real product identity) even when his photo
is just a plain unbranded decant vial with no distinguishable
manufacturer printed on it -- see extract.py's PROMPT_ALWAYS_DUPE_OVERRIDE.
Without --always-dupe, --dupe-pattern's normal "maybe it's genuine"
exception would (and, before this was added, silently did) misclassify
his cheap clones as the real Creed/Amouage/Xerjoff/etc. product, merging
them onto the same catalog entry as legitimate stores' real pricing.

Usage: whenever EsLam Nasser posts something new, copy the post's URL and
run:

    python update_eslam_nasser.py "https://www.facebook.com/groups/.../posts/..."

Needs GEMINI_API_KEY set (see extract.py's docstring for how to get a free
one) — or add --local to use Ollama offline instead. Commits locally when
done, never pushes; review with `git diff` / `git log` then push yourself.
"""
import subprocess
import sys
from pathlib import Path

STORE_NAME = "EsLam Nasser"
STORE_URL = "https://www.facebook.com/eslam.nasser.10/"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    post_url = sys.argv[1]
    extra_args = sys.argv[2:]  # e.g. --local

    cmd = [
        sys.executable, str(Path(__file__).parent / "extract.py"),
        "--dupe-pattern", "--always-dupe",
        "--store", STORE_NAME,
        "--url", STORE_URL,
        *extra_args,
        post_url,
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
