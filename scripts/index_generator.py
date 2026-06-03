#!/usr/bin/env python3
"""
Index Generator — Generate/update .vscode/drawio-code-links.json from drawio files.

This script scans drawio diagram files, extracts all code-linked nodes
(hedietLinkedDataV1_* attributes), and updates the reverse index used by
VS Code's "Jump to Diagram Node" feature.

Usage:
    # Update index for a specific diagram file
    python3 scripts/index_generator.py --drawio diagrams/arch.drawio

    # Scan all drawio files in a workspace
    python3 scripts/index_generator.py --workspace .

    # Dry run (show what would change without writing)
    python3 scripts/index_generator.py --workspace . --dry-run
"""

import os
import sys
import argparse
import json
from typing import List, Dict, Any, Optional, Set
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.xml_parser import XmlParser, NodeInfo
from scripts.utils.path_utils import get_line_count

INDEX_VERSION = 1
INDEX_FILENAME = "drawio-code-links.json"


def find_workspace_root(start_dir: str) -> Optional[str]:
    """Find workspace root by walking up looking for markers."""
    current = os.path.abspath(start_dir)
    markers = [".git", "package.json", "pyproject.toml", "go.mod", "Cargo.toml", ".vscode"]
    while current:
        for marker in markers:
            if os.path.exists(os.path.join(current, marker)):
                return current
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return None


EXCLUDE_DIRS = {"node_modules", ".git", ".svn", "__pycache__", ".venv", "venv", "dist", "build", ".next", "target"}

def find_drawio_files(workspace: str) -> List[str]:
    """Find all drawio files in a workspace, skipping common excludes."""
    patterns = ["*.drawio", "*.dio", "*.drawio.svg", "*.dio.svg"]
    files: List[str] = []
    root = Path(workspace).resolve()
    for pattern in patterns:
        for f in root.rglob(pattern):
            if not any(part in EXCLUDE_DIRS for part in f.relative_to(root).parts):
                files.append(str(f))
    return sorted(files)


def make_index_entry(
    node: NodeInfo,
    diagram_rel_path: str,
    workspace_root: str,
    drawio_abs: str,
) -> Optional[Dict[str, Any]]:
    """Create a single index entry from a drawio node.

    hedietLinkedDataV1_path is relative to the drawio FILE (because vscode-drawio's
    CodePosition.deserialize uses path.join(drawio_file_path, stored_path)).
    So we must join with drawio_abs (file), not drawio_dir.
    """
    if not node.path:
        return None

    # Join with the drawio FILE path (not dir) to match path.join behavior
    code_abs = os.path.normpath(os.path.join(drawio_abs, node.path))
    try:
        code_file = os.path.relpath(code_abs, workspace_root).replace(os.sep, "/")
    except ValueError:
        # Path is on different drive (Windows) — skip
        return None

    return {
        "codeFile": code_file,
        "startLine": node.start_line,
        "endLine": node.end_line,
        "symbol": node.symbol,
        "diagramFile": diagram_rel_path,
        "cellId": node.id,
        "cellLabel": node.label,
    }


def scan_drawio_file(
    drawio_path: str,
    workspace_root: str,
) -> List[Dict[str, Any]]:
    """Scan a single drawio file and return index entries."""
    drawio_abs = os.path.abspath(drawio_path)
    diagram_rel = os.path.relpath(drawio_abs, workspace_root).replace(os.sep, "/")

    parser = XmlParser(drawio_abs)
    data = parser.parse()

    entries: List[Dict[str, Any]] = []
    for node in data.nodes:
        entry = make_index_entry(node, diagram_rel, workspace_root, drawio_abs)
        if entry is not None:
            entries.append(entry)

    return entries


def read_existing_index(workspace_root: str) -> Dict[str, Any]:
    """Read existing index file if it exists."""
    index_path = os.path.join(workspace_root, ".vscode", INDEX_FILENAME)
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"version": INDEX_VERSION, "entries": []}


def write_index(workspace_root: str, entries: List[Dict[str, Any]]) -> None:
    """Write index entries to .vscode/drawio-code-links.json."""
    vscode_dir = os.path.join(workspace_root, ".vscode")
    os.makedirs(vscode_dir, exist_ok=True)

    index_path = os.path.join(vscode_dir, INDEX_FILENAME)
    data = {"version": INDEX_VERSION, "entries": entries}

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def update_index(
    workspace_root: str,
    drawio_files: List[str],
    dry_run: bool = False,
) -> int:
    """
    Update the index for the given drawio files.

    Returns the number of entries written.
    """
    existing = read_existing_index(workspace_root)
    old_entries: List[Dict[str, Any]] = existing.get("entries", [])

    # Collect the set of diagram files being scanned
    scanned_diagrams: Set[str] = set()
    for df in drawio_files:
        rel = os.path.relpath(os.path.abspath(df), workspace_root).replace(os.sep, "/")
        scanned_diagrams.add(rel)

    # Keep entries from diagrams NOT being scanned (incremental merge)
    new_entries = [e for e in old_entries if e.get("diagramFile") not in scanned_diagrams]

    # Scan each drawio file and add its entries
    for drawio_path in drawio_files:
        file_entries = scan_drawio_file(drawio_path, workspace_root)
        new_entries.extend(file_entries)

    if dry_run:
        stats = {
            "workspace": workspace_root,
            "diagrams_scanned": len(drawio_files),
            "entries_before": len(old_entries),
            "entries_after": len(new_entries),
            "entries_added": len(new_entries) - len(
                [e for e in old_entries if e.get("diagramFile") not in scanned_diagrams]
            ),
        }
        print(json.dumps(stats, indent=2, ensure_ascii=False))
        return len(new_entries)

    write_index(workspace_root, new_entries)
    return len(new_entries)


def update_index_for_diagram(
    drawio_path: str,
    workspace_root: str = None,
    dry_run: bool = False,
) -> int:
    """
    Convenience: update index for a single diagram.
    Auto-detects workspace root from drawio path if not provided.
    """
    drawio_abs = os.path.abspath(drawio_path)
    if not os.path.exists(drawio_abs):
        print(f"Error: file not found: {drawio_abs}", file=sys.stderr)
        return 0

    if workspace_root is None:
        guessed = find_workspace_root(os.path.dirname(drawio_abs))
        if guessed is None:
            print(
                "Error: cannot detect workspace root. "
                "Please specify --workspace explicitly.",
                file=sys.stderr,
            )
            return 0
        workspace_root = guessed

    return update_index(workspace_root, [drawio_abs], dry_run=dry_run)


def update_index_for_workspace(
    workspace_root: str,
    dry_run: bool = False,
) -> int:
    """Scan all drawio files in workspace and regenerate the index."""
    workspace_root = os.path.abspath(workspace_root)
    files = find_drawio_files(workspace_root)
    if not files:
        print(f"No drawio files found in {workspace_root}")
        return 0

    return update_index(workspace_root, files, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser(
        description="Generate/update .vscode/drawio-code-links.json from drawio files"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--drawio", "-d", help="Single drawio file to scan")
    group.add_argument("--workspace", "-w", help="Workspace root (scans all *.drawio files)")
    parser.add_argument("--dry-run", "-n", action="store_true", help="Preview changes without writing")
    args = parser.parse_args()

    if args.drawio:
        count = update_index_for_diagram(args.drawio, dry_run=args.dry_run)
    else:
        count = update_index_for_workspace(args.workspace, dry_run=args.dry_run)

    if args.dry_run:
        print(f"\nWould write {count} index entries")
    else:
        print(f"Index updated: {count} entries")


if __name__ == "__main__":
    main()
