#!/usr/bin/env python3
"""
Scan a directory tree for MP3 files and verify them with ffmpeg.

Each file is probed with:
    ffmpeg -v error -xerror -i <file> -f null -

Any file that makes ffmpeg exit with a non-zero status is reported on stdout as a
single line containing the file path and the first error message emitted by
ffmpeg. Files are probed in parallel worker threads for better throughput. The
script exits with code 0 even if corrupt files are encountered so that callers
can decide how to react.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import Iterable


def iter_mp3_files(root: Path) -> Iterable[Path]:
    """Yield every .mp3 file under root recursively."""
    for dirpath, _, filenames in os.walk(root):
        base = Path(dirpath)
        for name in filenames:
            if name.lower().endswith(".mp3"):
                yield base / name


def run_ffmpeg_check(ffmpeg: str, path: Path) -> tuple[int, str]:
    """
    Run ffmpeg against path and return (return_code, first_error_line).

    If ffmpeg exits with 0, the error line will be an empty string.
    """
    cmd = [
        ffmpeg,
        "-v",
        "error",
        "-xerror",
        "-i",
        str(path),
        "-f",
        "null",
        "-",
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return 0, ""

    combined = "\n".join(filter(None, (result.stderr, result.stdout)))
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped:
            return result.returncode, stripped
    return result.returncode, f"ffmpeg exited with status {result.returncode}"


def perform_check(ffmpeg: str, path: Path) -> tuple[Path, int, str]:
    """Return (path, return_code, error_line) for a single file."""
    return_code, error_line = run_ffmpeg_check(ffmpeg, path)
    return path, return_code, error_line


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Check all MP3 files in a directory tree with ffmpeg."
    )
    parser.add_argument(
        "root",
        type=Path,
        help="Directory to scan recursively.",
    )
    parser.add_argument(
        "--ffmpeg",
        default="ffmpeg",
        help="ffmpeg executable to use (default: %(default)s).",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress per-file success output; only corrupt files are logged.",
    )
    default_workers = max(1, min(32, os.cpu_count() or 1))
    parser.add_argument(
        "--workers",
        type=int,
        default=default_workers,
        help=(
            "Number of parallel ffmpeg checks to run (default: %(default)s). "
            "Setting this too high may overwhelm your system."
        ),
    )

    args = parser.parse_args(argv)
    root = args.root

    if not root.exists():
        parser.error(f"root path does not exist: {root}")
    if not root.is_dir():
        parser.error(f"root path is not a directory: {root}")
    if args.workers < 1:
        parser.error("--workers must be >= 1")

    total_checked = 0
    total_bad = 0
    mp3_files = list(iter_mp3_files(root))
    check_func = partial(perform_check, args.ffmpeg)

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            for mp3_path, return_code, error_line in executor.map(
                check_func, mp3_files
            ):
                total_checked += 1
                if return_code != 0:
                    total_bad += 1
                    print(f"[BAD] {mp3_path}: {error_line}")
                elif not args.quiet:
                    print(f"[OK ] {mp3_path}")
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130

    if total_bad == 0 and not args.quiet:
        print(f"Checked {total_checked} file(s); none reported errors.")
    elif total_bad > 0:
        print(
            f"Checked {total_checked} file(s); {total_bad} reported errors.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
