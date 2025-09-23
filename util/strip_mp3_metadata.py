#!/usr/bin/env python3
"""
strip_mp3_metadata.py
Remove ID3 metadata from MP3 files.

Usage:
  python3 strip_mp3_metadata.py [-r] [--dry-run] [PATH]

Options:
  -r, --recursive  Walk directories recursively.
  --dry-run        Report what would be stripped without writing changes.
"""

import argparse
import os
import stat
import sys
import tempfile
from typing import Iterator, Tuple


def synchsafe_to_int(data: bytes) -> int:
    """Convert a 4-byte synchsafe integer to a regular int."""
    value = 0
    for byte in data:
        value = (value << 7) | (byte & 0x7F)
    return value


def detect_id3v2(path: str) -> Tuple[bool, int]:
    """Return (has_tag, total_tag_size) for an ID3v2 header."""
    with open(path, "rb") as fh:
        header = fh.read(10)
        if len(header) < 10 or header[:3] != b"ID3":
            return False, 0

        flags = header[5]
        tag_body_size = synchsafe_to_int(header[6:10])
        tag_size = tag_body_size + 10
        if flags & 0x10:  # footer present
            tag_size += 10

        fh.seek(0, os.SEEK_END)
        if tag_size >= fh.tell():
            return False, 0  # corrupt tag; do nothing
        return True, tag_size


def detect_id3v1(path: str) -> bool:
    """Return True if an ID3v1 tag is present at the end of the file."""
    try:
        with open(path, "rb") as fh:
            fh.seek(-128, os.SEEK_END)
            return fh.read(3) == b"TAG"
    except OSError:
        return False


def strip_id3v2(path: str, tag_size: int) -> None:
    """Remove the ID3v2 segment at the start of the file."""
    tmp_path = None
    try:
        with open(path, "rb") as src:
            src.seek(tag_size)
            with tempfile.NamedTemporaryFile(
                "wb", delete=False, dir=os.path.dirname(path) or "."
            ) as tmp:
                tmp_path = tmp.name
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    tmp.write(chunk)
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def strip_id3v1(path: str) -> None:
    """Remove ID3v1 footer by truncating the last 128 bytes."""
    with open(path, "r+b") as fh:
        fh.seek(0, os.SEEK_END)
        if fh.tell() >= 128:
            fh.truncate(fh.tell() - 128)


def iter_mp3s(root: str, recursive: bool) -> Iterator[str]:
    """Yield MP3 file paths under root."""
    if recursive:
        for current, _, filenames in os.walk(root):
            for name in filenames:
                if name.lower().endswith(".mp3"):
                    full = os.path.join(current, name)
                    if os.path.isfile(full):
                        yield full
    else:
        for name in os.listdir(root):
            if name.lower().endswith(".mp3"):
                full = os.path.join(root, name)
                if os.path.isfile(full):
                    yield full


def process_file(path: str, has_v2: bool, v2_size: int, has_v1: bool) -> bool:
    """Strip any detected tags and restore original times/permissions."""
    if not (has_v2 or has_v1):
        return False

    stat_result = os.stat(path, follow_symlinks=False)
    mode = stat.S_IMODE(stat_result.st_mode)

    if has_v2:
        strip_id3v2(path, v2_size)
        os.chmod(path, mode)
    if has_v1:
        strip_id3v1(path)

    os.utime(path, (stat_result.st_atime, stat_result.st_mtime))
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Remove metadata from MP3 files.")
    parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Folder to process (default: current directory).",
    )
    parser.add_argument(
        "-r",
        "--recursive",
        action="store_true",
        help="Walk folders recursively.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report what would change without modifying files.",
    )
    args = parser.parse_args()

    target = os.path.abspath(args.path)
    if not os.path.isdir(target):
        print(f"Not a directory: {target}", file=sys.stderr)
        return 1

    mp3_paths = list(iter_mp3s(target, args.recursive))
    if not mp3_paths:
        print("No MP3 files found.")
        return 0

    processed = 0
    skipped = 0

    for mp3_path in mp3_paths:
        try:
            has_v2, v2_size = detect_id3v2(mp3_path)
            has_v1 = detect_id3v1(mp3_path)
        except OSError as exc:
            skipped += 1
            print(f"[skip] {mp3_path}: {exc}", file=sys.stderr)
            continue

        if args.dry_run:
            if has_v2 or has_v1:
                tags = []
                if has_v2:
                    tags.append("ID3v2")
                if has_v1:
                    tags.append("ID3v1")
                print(f"[dry-run] would remove {' + '.join(tags)}: {mp3_path}")
            continue

        try:
            if process_file(mp3_path, has_v2, v2_size, has_v1):
                processed += 1
                print(f"[ok] stripped metadata: {mp3_path}")
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            print(f"[error] {mp3_path}: {exc}", file=sys.stderr)

    if not args.dry_run:
        print(f"Done. Updated {processed} file(s); skipped {skipped}.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
