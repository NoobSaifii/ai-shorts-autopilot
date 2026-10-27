"""Disk-space helpers.

The GitHub runner only has ~14GB free and one video's intermediates
(silent scenes + muxed scenes + raw wavs) weigh ~900MB, so leftovers from
earlier channels are what exhaust the disk mid-render.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger("pipeline.disk")


def _mount_point(path) -> Path:
    p = Path(path)
    try:
        p = p.resolve()
    except OSError:
        pass
    while not p.exists() and p != p.parent:
        p = p.parent
    return p


def free_gb(path=".") -> float:
    """Free space on the filesystem holding `path`, in GB (-1 if unknown)."""
    try:
        return shutil.disk_usage(_mount_point(path)).free / 1024**3
    except OSError:
        return -1.0


def size_mb(path) -> float:
    p = Path(path)
    if not p.exists():
        return 0.0
    if p.is_file():
        try:
            return p.stat().st_size / 1024**2
        except OSError:
            return 0.0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total / 1024**2


def purge(path, label: str = "") -> float:
    """Delete a file or directory tree. Returns MB freed. Never raises."""
    p = Path(path)
    if not p.exists():
        return 0.0
    freed = size_mb(p)
    try:
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        else:
            p.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"cleanup: could not remove {p} — {e}")
        return 0.0
    if freed >= 1:
        logger.info(f"cleanup: freed {freed:.0f}MB ({label or p.name})")
    return freed


def log_free(tag: str, path=".") -> float:
    g = free_gb(path)
    logger.info(f"disk: {g:.1f}GB free — {tag}")
    return g
