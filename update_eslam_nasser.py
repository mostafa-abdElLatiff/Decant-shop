#!/usr/bin/env python3
"""
update_eslam_nasser.py — add EsLam Nasser's latest Facebook post to the catalogue.

EsLam Nasser posts local-brand decant bottles "inspired by" a named
designer/niche fragrance — a price banner names the reference fragrance
while a separate photo shows the actual bottle for sale, so this always
runs extract.py with --dupe-pattern.

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
        "--dupe-pattern",
        "--store", STORE_NAME,
        "--url", STORE_URL,
        *extra_args,
        post_url,
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
