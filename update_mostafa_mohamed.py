#!/usr/bin/env python3
"""
update_mostafa_mohamed.py — add Mostafa Mohamed's latest Facebook post to the catalogue.

Mostafa Mohamed sells decants/full bottles/leftovers of the genuine named
fragrance directly — no "dupe of" reference pattern — so this runs
extract.py *without* --dupe-pattern. Remember: only mark something a "full"
bottle if the post explicitly says so; if it's a used/remaining bottle with
no stated quantity, extract.py will record it as "as-shown" rather than
guess a number from the box.

Usage: whenever Mostafa Mohamed posts something new, copy the post's URL
and run:

    python update_mostafa_mohamed.py "https://www.facebook.com/groups/.../posts/..."

Needs GEMINI_API_KEY set (see extract.py's docstring for how to get a free
one) — or add --local to use Ollama offline instead. Commits locally when
done, never pushes; review with `git diff` / `git log` then push yourself.
"""
import subprocess
import sys
from pathlib import Path

STORE_NAME = "Mostafa Mohamed"
STORE_URL = "https://www.facebook.com/mostafa.mohamed.390048/"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    post_url = sys.argv[1]
    extra_args = sys.argv[2:]  # e.g. --local

    cmd = [
        sys.executable, str(Path(__file__).parent / "extract.py"),
        "--store", STORE_NAME,
        "--url", STORE_URL,
        *extra_args,
        post_url,
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
