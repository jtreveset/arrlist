#!/usr/bin/env python3
"""
Generate artists.json from a list of artist names using the MusicBrainz API.

Usage:
  python generate_artists_json.py input.txt artists.json

Where input.txt contains one artist name per line.

Notes:
  - Respects MusicBrainz rate limits (default ~1 request/sec).
  - Chooses the highest-scoring search result, preferring exact name matches.
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError


# Application metadata
APP_NAME = "arrlist-generator"
APP_VERSION = "0.1.0"  # Update this to bump the suggested User-Agent version
APP_URL = "https://github.com/jtreveset/arrlist"
DEFAULT_USER_AGENT = f"{APP_NAME}/{APP_VERSION} ({APP_URL})"

MB_BASE_URL = "https://musicbrainz.org/ws/2/artist"


def normalize_name(name: str) -> str:
    return " ".join(name.split()).strip().lower()


def fetch_json(url: str, params: Optional[Dict[str, Any]], user_agent: str, timeout: int = 30):
    if params:
        query_str = urllib.parse.urlencode(params)
        url = f"{url}?{query_str}"
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        data = resp.read()
        return json.loads(data.decode(charset)), resp.headers


def search_artist_mbid(name: str, user_agent: str, retries: int = 3, delay: float = 1.1) -> Optional[str]:
    # Use quoted phrase search on the artist field
    # Escape embedded quotes to keep a valid phrase query
    safe_name = name.replace('"', '\\"')
    query = f'artist:"{safe_name}"'
    params = {"query": query, "fmt": "json"}

    attempt = 0
    while attempt <= retries:
        try:
            data, headers = fetch_json(MB_BASE_URL, params=params, user_agent=user_agent)
            artists = data.get("artists") or []
            if not artists:
                return None

            target = normalize_name(name)
            exact = [a for a in artists if normalize_name(a.get("name", "")) == target]

            def score(a):
                try:
                    return int(a.get("score", 0))
                except Exception:
                    return 0

            selected = max(exact or artists, key=score)
            return selected.get("id")

        except HTTPError as e:
            # Handle rate limiting/backoff
            retry_after = None
            if getattr(e, "headers", None):
                ra = e.headers.get("Retry-After")
                if ra:
                    try:
                        retry_after = float(ra)
                    except ValueError:
                        retry_after = None

            if e.code in (429, 503) or retry_after is not None:
                wait = retry_after if retry_after is not None else (delay * (2 ** attempt))
                time.sleep(wait)
                attempt += 1
                continue

            sys.stderr.write(f"HTTP error for '{name}': {e}\n")
            return None

        except URLError as e:
            sys.stderr.write(f"Network error for '{name}': {e}\n")
            time.sleep(delay * (2 ** attempt))
            attempt += 1
            continue

    return None


def read_names(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            yield s


def write_artists_json(mbids: List[str], output_path: str):
    # Match the example format: one compact object per line with two-space indent
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("[\n")
        for i, mbid in enumerate(mbids):
            comma = "," if i < len(mbids) - 1 else ""
            f.write(f'  {{ "MusicBrainzId": "{mbid}" }}{comma}\n')
        f.write("]\n")


def main():
    parser = argparse.ArgumentParser(
        description="Generate artists.json from a list of artist names using the MusicBrainz API.",
    )
    parser.add_argument("input", help="Path to text file with one artist name per line")
    parser.add_argument("output", help="Path to output JSON file (e.g., artists.json)")
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help=f"User-Agent for MusicBrainz (default: {DEFAULT_USER_AGENT})",
    )
    parser.add_argument("--delay", type=float, default=1.1, help="Delay between requests in seconds")
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts for transient errors")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit with error if any artist cannot be resolved",
    )

    args = parser.parse_args()

    names = list(read_names(args.input))
    if not names:
        sys.stderr.write("No artist names found in input.\n")
        write_artists_json([], args.output)
        return

    mbids: List[str] = []
    for idx, name in enumerate(names):
        mbid = search_artist_mbid(name, user_agent=args.user_agent, retries=args.retries, delay=args.delay)
        if mbid is None:
            sys.stderr.write(f"Warning: No MusicBrainz ID found for '{name}'\n")
            if args.strict:
                sys.exit(f"Failed to resolve artist: {name}")
        else:
            mbids.append(mbid)

        # Respect MusicBrainz 1 req/sec guideline
        if idx < len(names) - 1:
            time.sleep(args.delay)

    write_artists_json(mbids, args.output)


if __name__ == "__main__":
    main()
