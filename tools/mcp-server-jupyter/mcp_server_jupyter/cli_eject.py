#!/usr/bin/env python3
"""
mcp-jupyter-eject: Cleanup tool to uninstall MCP Jupyter and remove all traces.

Usage:
  python -m tools.mcp_server_jupyter.cli.eject [--archive-assets]

This script:
  1. Strips all mcp_* metadata from notebooks in the current directory and subdirectories.
  2. Deletes the .mcp-jupyter/ config directory (if present).
  3. Optionally archives the assets/ folder to assets-backup.tar.gz before deletion.

It is safe to run multiple times; idempotent operations.
"""

import argparse
import json
import shutil
import tarfile
from pathlib import Path


def find_notebooks(start_dir: Path = None) -> list[Path]:
    """Recursively find all .ipynb files."""
    if start_dir is None:
        start_dir = Path.cwd()
    return sorted(start_dir.rglob("*.ipynb"))


def strip_mcp_metadata(notebook_path: Path) -> bool:
    """
    Remove all mcp_* keys from notebook metadata.
    Returns True if modified, False otherwise.
    """
    try:
        with open(notebook_path, "r", encoding="utf-8") as f:
            nb = json.load(f)
    except Exception as e:
        print(f"⚠️  Could not read {notebook_path}: {e}")
        return False

    modified = False

    # Strip notebook-level metadata
    if "metadata" in nb:
        keys_to_remove = [k for k in nb["metadata"].keys() if k.startswith("mcp_")]
        if keys_to_remove:
            for k in keys_to_remove:
                del nb["metadata"][k]
            modified = True

    # Strip cell-level metadata
    if "cells" in nb:
        for cell in nb["cells"]:
            if "metadata" in cell:
                cell_keys = [k for k in cell["metadata"].keys() if k.startswith("mcp_")]
                if cell_keys:
                    for k in cell_keys:
                        del cell["metadata"][k]
                    modified = True

    if modified:
        try:
            with open(notebook_path, "w", encoding="utf-8") as f:
                json.dump(nb, f, indent=2, ensure_ascii=False)
            print(f"✅ Stripped metadata from {notebook_path}")
        except Exception as e:
            print(f"❌ Could not write to {notebook_path}: {e}")
            return False

    return modified


def remove_config_directory(config_dir: Path = None) -> bool:
    """Remove the .mcp-jupyter config directory."""
    if config_dir is None:
        config_dir = Path.home() / ".mcp-jupyter"

    if config_dir.exists():
        try:
            shutil.rmtree(config_dir)
            print(f"✅ Deleted config directory: {config_dir}")
            return True
        except Exception as e:
            print(f"❌ Could not delete {config_dir}: {e}")
            return False
    else:
        print(f"ℹ️  Config directory not found: {config_dir}")
        return False


def archive_and_remove_assets(
    assets_dir: Path = None, archive_path: Path = None
) -> bool:
    """Archive assets/ to a tar.gz, then delete the directory."""
    if assets_dir is None:
        assets_dir = Path.cwd() / "assets"

    if not assets_dir.exists():
        print(f"ℹ️  Assets directory not found: {assets_dir}")
        return False

    if archive_path is None:
        archive_path = Path.cwd() / "assets-backup.tar.gz"

    try:
        print(f"📦 Archiving assets to {archive_path}...")
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(assets_dir, arcname="assets")
        print(f"✅ Archived to {archive_path}")

        shutil.rmtree(assets_dir)
        print(f"✅ Deleted assets directory: {assets_dir}")
        return True
    except Exception as e:
        print(f"❌ Archive/delete failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Remove all MCP Jupyter traces from the current notebook environment."
    )
    parser.add_argument(
        "--archive-assets",
        action="store_true",
        help="Archive assets/ to assets-backup.tar.gz before deletion (optional).",
    )
    parser.add_argument(
        "--notebook-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory to search for notebooks (default: current directory).",
    )

    args = parser.parse_args()

    print("🚀 Starting MCP Jupyter cleanup (eject)...\n")

    # Find and strip notebooks
    notebooks = find_notebooks(args.notebook_dir)
    if notebooks:
        print(f"📓 Found {len(notebooks)} notebook(s):")
        modified_count = 0
        for nb in notebooks:
            if strip_mcp_metadata(nb):
                modified_count += 1
        print(f"✅ Stripped metadata from {modified_count} notebook(s)\n")
    else:
        print(f"ℹ️  No notebooks found in {args.notebook_dir}\n")

    # Remove config directory
    remove_config_directory()
    print()

    # Archive and remove assets (optional)
    if args.archive_assets:
        archive_and_remove_assets()
    else:
        assets_dir = args.notebook_dir / "assets"
        if assets_dir.exists():
            print("💡 Tip: Use --archive-assets to backup assets/ before deletion.")
            print(f"    Assets directory: {assets_dir}\n")

    print("🎉 Cleanup complete! MCP Jupyter has been uninstalled.")
    print("💼 Your notebooks are now clean and portable.\n")


if __name__ == "__main__":
    main()
