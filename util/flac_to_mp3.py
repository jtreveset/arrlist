#!/usr/bin/env python3
"""Traverse directories and re-encode lossless audio files to 320kbps MP3."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Re-encode FLAC, WAV, or lossless M4A files within a directory tree to 320kbps MP3 files.",
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Root directory to scan for lossless audio files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List the actions that would be taken without invoking ffmpeg or removing files.",
    )
    parser.add_argument(
        "--remove-original",
        action="store_true",
        help="Remove each original lossless file after a successful conversion.",
    )
    return parser.parse_args()


SUPPORTED_EXTENSIONS = {".flac", ".m4a", ".wav"}


def iter_lossless_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def convert_source(source_path: Path, dry_run: bool = False) -> bool:
    mp3_path = source_path.with_suffix(".mp3")
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(source_path),
        "-vn",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        str(mp3_path),
    ]
    if dry_run:
        print(f"[dry-run] Would encode '{source_path}' -> '{mp3_path}'")
        return True

    print(f"Encoding '{source_path}' -> '{mp3_path}'")
    try:
        result = subprocess.run(cmd, check=True)
    except FileNotFoundError:
        print("Error: ffmpeg not found. Ensure ffmpeg is installed and on PATH.", file=sys.stderr)
        return False
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed for '{source_path}' with exit code {exc.returncode}.", file=sys.stderr)
        return False

    return result.returncode == 0


def remove_original(source_path: Path, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"[dry-run] Would remove '{source_path}'")
        return True

    try:
        source_path.unlink()
    except OSError as exc:
        print(f"Failed to remove '{source_path}': {exc}", file=sys.stderr)
        return False

    print(f"Removed '{source_path}'")
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

    source_files = list(iter_lossless_files(root))
    if not source_files:
        print("No FLAC, WAV, or lossless M4A files found; nothing to do.")
        return

    failed = 0
    total = len(source_files)
    for index, source_file in enumerate(source_files, start=1):
        converted_ok = convert_source(source_file, dry_run=args.dry_run)
        if not converted_ok:
            failed += 1
        elif args.remove_original and not remove_original(source_file, dry_run=args.dry_run):
            failed += 1

        percent_complete = (index / total) * 100
        print(f"{index}/{total} files processed ({percent_complete:.1f}%)")

    if failed:
        print(f"Completed with {failed} failure(s).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
