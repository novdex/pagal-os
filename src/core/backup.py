"""PAGAL OS Backup & Restore — full system backup in one zip file.

Creates compressed backups of all agent YAMLs, databases, configs,
and JSON state files. Supports restore, auto-rotation (keep last 7),
and listing available backups.

Backup directory: ``~/.pagal-os/backups/``
"""

import json
import logging
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("pagal_os")

# Paths
_PAGAL_DIR = Path.home() / ".pagal-os"
BACKUPS_DIR = _PAGAL_DIR / "backups"

# Files and directories to include in a backup
_BACKUP_TARGETS: list[str] = [
    "agents",            # directory — all agent YAMLs
    "pagal.db",          # main database (memory, knowledge, analytics)
    "credits.db",        # credits database
    "traces.db",         # observability traces
    "marketplace.json",  # marketplace state
    "registry.json",     # agent registry
    "hands.json",        # scheduled hands state
    "worlds.json",       # worlds state
    "versions",          # directory — agent version history
]


def _ensure_backups_dir() -> None:
    """Create the backups directory if it doesn't exist."""
    try:
        BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.error("Failed to create backups directory: %s", e)


def _timestamp_str() -> str:
    """Return a filesystem-safe timestamp string.

    Returns:
        Timestamp like '20260330_143021'.
    """
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def create_backup() -> str:
    """Create a full system backup as a zip file.

    Backs up all agent YAMLs, databases, config files, and state files
    from ``~/.pagal-os/``.

    Returns:
        Absolute path to the created backup zip file.

    Raises:
        RuntimeError: If no files were found to back up.
    """
    _ensure_backups_dir()
    backup_name = f"pagal_backup_{_timestamp_str()}.zip"
    backup_path = BACKUPS_DIR / backup_name

    try:
        files_added = 0
        with zipfile.ZipFile(backup_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for target in _BACKUP_TARGETS:
                target_path = _PAGAL_DIR / target
                if not target_path.exists():
                    continue

                if target_path.is_dir():
                    for file in target_path.rglob("*"):
                        if file.is_file():
                            arcname = str(file.relative_to(_PAGAL_DIR))
                            zf.write(file, arcname)
                            files_added += 1
                else:
                    arcname = str(target_path.relative_to(_PAGAL_DIR))
                    zf.write(target_path, arcname)
                    files_added += 1

        if files_added == 0:
            backup_path.unlink(missing_ok=True)
            raise RuntimeError("No files found to back up")

        logger.info("Backup created: %s (%d files)", backup_path, files_added)
        return str(backup_path)
    except RuntimeError:
        raise
    except Exception as e:
        logger.error("Backup creation failed: %s", e)
        raise


def restore_backup(backup_path: str) -> dict[str, Any]:
    """Restore a system backup from a zip file.

    Extracts all files from the backup zip into ``~/.pagal-os/``,
    overwriting existing files.

    Args:
        backup_path: Path to the backup zip file.

    Returns:
        Dict with 'ok' status and list of restored file names.

    Raises:
        FileNotFoundError: If the backup file doesn't exist.
        zipfile.BadZipFile: If the file is not a valid zip.
    """
    path = Path(backup_path)
    if not path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    try:
        restored: list[str] = []
        with zipfile.ZipFile(path, "r") as zf:
            for member in zf.namelist():
                # Security: prevent path traversal
                target = _PAGAL_DIR / member
                resolved = target.resolve()
                if not str(resolved).startswith(str(_PAGAL_DIR.resolve())):
                    logger.warning("Skipping suspicious path in backup: %s", member)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                restored.append(member)

        logger.info("Restored backup from %s (%d files)", backup_path, len(restored))
        return {"ok": True, "restored": restored}
    except Exception as e:
        logger.error("Backup restore failed: %s", e)
        return {"ok": False, "error": str(e), "restored": []}


def list_backups() -> list[dict[str, Any]]:
    """List all available backup files with date and size.

    Returns:
        List of dicts with 'filename', 'path', 'date', and 'size_mb' keys,
        sorted newest first.
    """
    _ensure_backups_dir()
    backups: list[dict[str, Any]] = []

    try:
        for f in sorted(BACKUPS_DIR.glob("pagal_backup_*.zip"), reverse=True):
            stat = f.stat()
            backups.append({
                "filename": f.name,
                "path": str(f),
                "date": datetime.fromtimestamp(
                    stat.st_mtime, tz=timezone.utc,
                ).isoformat(),
                "size_mb": round(stat.st_size / (1024 * 1024), 2),
            })
    except Exception as e:
        logger.error("Failed to list backups: %s", e)

    return backups


def auto_backup() -> str:
    """Create a backup and rotate old backups (keep last 7).

    Designed to be called daily by a Hand (scheduled agent).

    Returns:
        Absolute path to the new backup file.
    """
    # Create new backup
    backup_path = create_backup()

    # Rotate: keep only the 7 most recent backups
    try:
        all_backups = sorted(
            BACKUPS_DIR.glob("pagal_backup_*.zip"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old_backup in all_backups[7:]:
            old_backup.unlink(missing_ok=True)
            logger.info("Rotated old backup: %s", old_backup.name)
    except Exception as e:
        logger.warning("Backup rotation failed: %s", e)

    return backup_path


def get_backup_size() -> dict[str, Any]:
    """Calculate the total size of all data that would be backed up.

    Returns:
        Dict with 'total_size_mb', 'files_count', and per-target breakdown.
    """
    total_size = 0
    files_count = 0
    breakdown: dict[str, float] = {}

    for target in _BACKUP_TARGETS:
        target_path = _PAGAL_DIR / target
        target_size = 0

        if not target_path.exists():
            continue

        try:
            if target_path.is_dir():
                for f in target_path.rglob("*"):
                    if f.is_file():
                        target_size += f.stat().st_size
                        files_count += 1
            else:
                target_size = target_path.stat().st_size
                files_count += 1
        except Exception:
            continue

        total_size += target_size
        breakdown[target] = round(target_size / (1024 * 1024), 3)

    return {
        "total_size_mb": round(total_size / (1024 * 1024), 2),
        "files_count": files_count,
        "breakdown": breakdown,
    }
