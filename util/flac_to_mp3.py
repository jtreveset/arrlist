#!/usr/bin/env python3
"""Traverse directories and re-encode FLAC files to 320kbps MP3."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-encode FLAC files within a directory tree to 320kbps MP3 files.",
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Root directory to scan for FLAC files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the actions that would be taken without invoking ffmpeg or removing files.",
    )
    parser.add_argument(
        "--remove-original",
        action="store_true",
        help="Remove each original FLAC file after a successful conversion.",
    )
    return parser.parse_args()


def iter_flac_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() == ".flac":
            yield path


def convert_flac(flac_path: Path, dry_run: bool = False) -> bool:
    mp3_path = flac_path.with_suffix(".mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(flac_path),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        str(mp3_path),
    ]
    if dry_run:
        print(f"[dry-run] Would encode '{flac_path}' -> '{mp3_path}'")
        return True

    print(f"Encoding '{flac_path}' -> '{mp3_path}'")
    try:
        result = subprocess.run(cmd, check=True)
    except FileNotFoundError:
        print("Error: ffmpeg not found. Ensure ffmpeg is installed and on PATH.", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed for '{flac_path}' with exit code {exc.returncode}.", file=sys.stderr)
        return False

    return result.returncode == 0


def remove_original(flac_path: Path, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[dry-run] Would remove '{flac_path}'")
        return True

    try:
        flac_path.unlink()
    except OSError as exc:
        print(f"Failed to remove '{flac_path}': {exc}", file=sys.stderr)
        return False

    print(f"Removed '{flac_path}'")
    return True


def main() -> None:
    args = parse_args()
    root = args.root.expanduser().resolve()

    if not root.exists():
        print(f"Error: '{root}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if not root.is_dir():
        print(f"Error: '{root}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    flac_files = list(iter_flac_files(root))
    if not flac_files:
        print("No FLAC files found; nothing to do.")
        return

    failed = 0
    for flac_file in flac_files:
        if not convert_flac(flac_file, dry_run=args.dry_run):
            failed += 1
            continue

        if args.remove_original and not remove_original(flac_file, dry_run=args.dry_run):
            failed += 1

    if failed:
        print(f"Completed with {failed} failure(s).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
