#!/usr/bin/env python3
"""
update_hossam_eldeen_gamal.py — add Hossam ElDeen Gamal's latest Facebook post.

Hossam ElDeen Gamal writes each photo's fragrance name in that photo's own
Facebook caption (visible per-image in a multi-photo post), while sizes and
prices are only printed inside the image itself. This always runs
extract.py with --use-captions so the caption is trusted for the name
instead of guessed from the image — the image only has to supply
brand/notes/sizes/prices. Sells genuine decants directly (no dupe-of-a-
different-fragrance pattern), so no --dupe-pattern.

Usage: whenever Hossam ElDeen Gamal posts something new, copy the post's
URL and run:

    python update_hossam_eldeen_gamal.py "https://www.facebook.com/groups/.../posts/..."

Needs GEMINI_API_KEY set (see extract.py's docstring for how to get a free
one) — or add --local to use Ollama offline instead. Commits locally when
done, never pushes; review with `git diff` / `git log` then push yourself.
"""
import subprocess
import sys
from pathlib import Path

STORE_NAME = "Hossam ElDeen Gamal"
STORE_URL = "https://www.facebook.com/hossameldeien/"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    post_url = sys.argv[1]
    extra_args = sys.argv[2:]  # e.g. --local

    cmd = [
        sys.executable, str(Path(__file__).parent / "extract.py"),
        "--use-captions",
        "--store", STORE_NAME,
        "--url", STORE_URL,
        *extra_args,
        post_url,
    ]
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
