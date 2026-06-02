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
import tempfile
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


def _first_ffmpeg_message(
    result: subprocess.CompletedProcess[str],
) -> str:
    combined = "\n".join(filter(None, (result.stderr, result.stdout)))
    for line in combined.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def run_ffmpeg_check(ffmpeg: str, path: Path) -> tuple[int, str]:
    """
    Run ffmpeg against path and return (return_code, first_error_line).

    If ffmpeg exits with 0, the error line will be an empty string.
    """
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
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

    message = _first_ffmpeg_message(result)
    if message:
        return result.returncode, message
    return result.returncode, f"ffmpeg exited with status {result.returncode}"


def perform_check(ffmpeg: str, path: Path) -> tuple[Path, int, str]:
    """Return (path, return_code, error_line) for a single file."""
    return_code, error_line = run_ffmpeg_check(ffmpeg, path)
    return path, return_code, error_line


def detect_fatal_breakage(ffmpeg: str, path: Path) -> tuple[bool, str]:
    """
    Try to detect whether a file is fatally broken before fix attempts.

    We ask ffmpeg to decode a couple of frames; if it cannot, we treat it as
    fatal and avoid destructive work on the file.
    """
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "fatal",
        "-xerror",
        "-i",
        str(path),
        "-frames:a",
        "5",
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
        return False, ""

    message = _first_ffmpeg_message(result)
    if not message:
        message = "ffmpeg failed while probing file"
    return True, message


def _reserve_backup_path(path: Path) -> Path:
    original_name = path.name
    for index in range(1000):
        suffix = ".bak" if index == 0 else f".bak{index}"
        candidate = path.with_name(original_name + suffix)
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Could not allocate backup filename for {path}")


def attempt_fix(ffmpeg: str, path: Path) -> tuple[bool, str]:
    """
    Attempt to repair a corrupt MP3 file in place by re-encoding it.

    The original file is preserved with a '.bak' suffix on success.
    """
    fd, tmp_name = tempfile.mkstemp(suffix=".mp3", dir=path.parent)
    os.close(fd)
    tmp_path = Path(tmp_name)

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-v",
        "error",
        "-y",
        "-i",
        str(path),
        "-map",
        "0:a:0?",
        "-vn",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        str(tmp_path),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = _first_ffmpeg_message(result) or "ffmpeg failed to re-encode file"
        tmp_path.unlink(missing_ok=True)
        return False, message

    verify_code, verify_message = run_ffmpeg_check(ffmpeg, tmp_path)
    if verify_code != 0:
        tmp_path.unlink(missing_ok=True)
        if not verify_message:
            verify_message = "verification failed after fix attempt"
        return False, verify_message

    try:
        backup_path = _reserve_backup_path(path)
    except RuntimeError as exc:
        tmp_path.unlink(missing_ok=True)
        return False, str(exc)

    try:
        path.rename(backup_path)
    except OSError as exc:
        tmp_path.unlink(missing_ok=True)
        return False, f"failed to back up original file: {exc}"

    try:
        tmp_path.rename(path)
    except OSError as exc:
        # Best-effort: restore original file and clean up temporary output.
        backup_path.rename(path)
        tmp_path.unlink(missing_ok=True)
        return False, f"failed to finalize repaired file: {exc}"

    return True, f"rewrote file; backup stored at {backup_path.name}"


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
    parser.add_argument(
        "--fix",
        action="store_true",
        help=(
            "Attempt to repair corrupt files in place by re-encoding them. "
            "Original files are backed up with a '.bak' suffix."
        ),
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
    bad_results: list[tuple[Path, str]] = []
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
                    bad_results.append((mp3_path, error_line))
                    print(f"[BAD] {mp3_path}: {error_line}")
                elif not args.quiet:
                    print(f"[OK ] {mp3_path}")
    except KeyboardInterrupt:
        print("Interrupted by user.", file=sys.stderr)
        return 130

    total_fixed = 0
    total_fatal = 0
    total_fix_failed = 0

    if args.fix and bad_results:
        for mp3_path, error_line in bad_results:
            fatal, fatal_message = detect_fatal_breakage(args.ffmpeg, mp3_path)
            if fatal:
                total_fatal += 1
                message = fatal_message or error_line or "fatal corruption detected"
                print(f"[SKIP] {mp3_path}: {message}")
                continue

            fixed, fix_message = attempt_fix(args.ffmpeg, mp3_path)
            if fixed:
                total_fixed += 1
                print(f"[FIX] {mp3_path}: {fix_message}")
            else:
                total_fix_failed += 1
                message = fix_message or "fix attempt failed"
                print(f"[FAIL] {mp3_path}: {message}")

    if total_bad == 0 and not args.quiet:
        print(f"Checked {total_checked} file(s); none reported errors.")
    elif total_bad > 0:
        print(
            f"Checked {total_checked} file(s); {total_bad} reported errors.",
            file=sys.stderr,
        )
        if args.fix:
            print(
                (
                    f"Fix attempts: {total_fixed} succeeded, "
                    f"{total_fatal} skipped as fatal, "
                    f"{total_fix_failed} failed."
                ),
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
