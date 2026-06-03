#!/usr/bin/env python3
"""
Code Sync — Synchronize drawio diagram nodes with code files (Incremental).

Supports:
- Incremental line number updates (only changed nodes)
- Precise line range detection via regex/AST patterns
- Bidirectional sync (code → diagram, diagram → code)

Usage:
    # Update all line numbers in diagram
    python code_sync.py --drawio diagram.drawio --project-root . --update-lines --sync

    # Dry run to preview changes
    python code_sync.py --drawio diagram.drawio --project-root . --update-lines

    # Sync only specific nodes
    python code_sync.py --drawio diagram.drawio --project-root . --nodes user_svc,order_svc --sync
"""

import os
import sys
import argparse
import json
import shutil
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.xml_parser import XmlParser, DiagramData, NodeInfo
from scripts.utils.path_utils import PathResolver, get_line_count
from scripts.analyzer import find_block


@dataclass
class SyncAction:
    """Represents a synchronization action."""
    node_id: str
    node_label: str
    action_type: str
    field: str
    old_value: Any
    new_value: Any


@dataclass
class SyncResult:
    """Result of a synchronization operation."""
    success: bool
    actions: List[SyncAction]
    errors: List[Dict[str, Any]]
    nodes_updated: int
    backup_file: Optional[str] = None


class CodeSynchronizer:
    """Synchronize drawio diagram nodes with code files."""

    def __init__(
        self,
        drawio_file: str,
        project_root: Optional[str] = None,
        dry_run: bool = True,
        node_filter: Optional[List[str]] = None
    ):
        self.drawio_file = os.path.abspath(drawio_file)
        self.project_root = project_root or self._find_project_root()
        self.dry_run = dry_run
        self.node_filter = set(node_filter) if node_filter else None
        self.parser = XmlParser(drawio_file)
        self.data: Optional[DiagramData] = None
        self.resolver = PathResolver(drawio_file, self.project_root)
        self.actions: List[SyncAction] = []
        self.errors: List[Dict[str, Any]] = []

    def _find_project_root(self) -> str:
        """Find project root by looking for common markers."""
        current = os.path.dirname(os.path.abspath(self.drawio_file))
        markers = ["package.json", "tsconfig.json", ".git", "pyproject.toml", "go.mod", "Cargo.toml"]

        while current:
            for marker in markers:
                if os.path.exists(os.path.join(current, marker)):
                    return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

        return os.path.dirname(os.path.dirname(os.path.abspath(self.drawio_file)))

    def run(self, update_lines: bool = True, update_labels: bool = False) -> SyncResult:
        """Run the synchronization process."""
        print(f"Loading drawio file: {self.drawio_file}")
        print(f"Project root: {self.project_root}")

        if not os.path.exists(self.drawio_file):
            return SyncResult(
                success=False,
                actions=[],
                errors=[{"error": f"File not found: {self.drawio_file}"}],
                nodes_updated=0
            )

        try:
            self.data = self.parser.load(self.drawio_file)
        except Exception as e:
            return SyncResult(
                success=False,
                actions=[],
                errors=[{"error": f"Failed to parse XML: {str(e)}"}],
                nodes_updated=0
            )

        print(f"Found {len(self.data.nodes)} nodes")

        for node in self.data.nodes:
            # Skip if not in filter
            if self.node_filter and node.id not in self.node_filter:
                continue

            if node.path:
                if update_lines:
                    self._update_line_numbers_precise(node)
                if update_labels:
                    self._update_label(node)

        result = SyncResult(
            success=len(self.errors) == 0,
            actions=self.actions,
            errors=self.errors,
            nodes_updated=len(set(a.node_id for a in self.actions))
        )

        if not self.dry_run and self.actions:
            result.backup_file = self._apply_changes()

        return result

    def _update_line_numbers_precise(self, node: NodeInfo) -> None:
        """Update line numbers for a node using precise detection."""
        full_path = self._resolve_node_path(node)

        if not full_path or not os.path.exists(full_path):
            self.errors.append({
                "node_id": node.id,
                "label": node.label,
                "path": node.path,
                "error": "Could not resolve file path"
            })
            return

        # Read file content
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                lines = content.split('\n')
        except Exception as e:
            self.errors.append({
                "node_id": node.id,
                "label": node.label,
                "error": f"Failed to read file: {e}"
            })
            return

        # Try to find precise line range via AI+AST
        search_name = re.sub(r'\s*\([^)]*\)\s*', '', node.label).strip()
        search_name = search_name.replace('()', '')
        # Also try removing spaces for PascalCase class names like "User Service" -> "UserService"
        compact_name = search_name.replace(' ', '')
        start_line, end_line = find_block(full_path, search_name)
        if start_line is None and compact_name != search_name:
            start_line, end_line = find_block(full_path, compact_name)

        if start_line is None:
            self.errors.append({
                "node_id": node.id,
                "label": node.label,
                "error": f"Could not find block '{search_name}' in {full_path}"
            })
            return

        if node.start_line != start_line:
            self.actions.append(SyncAction(
                node_id=node.id,
                node_label=node.label,
                action_type="update",
                field="hedietLinkedDataV1_start_line_x-num",
                old_value=node.start_line,
                new_value=start_line
            ))

        if node.end_line != end_line:
            self.actions.append(SyncAction(
                node_id=node.id,
                node_label=node.label,
                action_type="update",
                field="hedietLinkedDataV1_end_line_x-num",
                old_value=node.end_line,
                new_value=end_line
            ))

    def _update_label(self, node: NodeInfo) -> None:
        """Update node label based on code content."""
        # TODO: Implement if needed
        pass

    def _resolve_node_path(self, node: NodeInfo) -> Optional[str]:
        """Resolve a node's path to an absolute file path."""
        if not node.path:
            return None

        drawio_dir = os.path.dirname(self.drawio_file)

        full_path = os.path.join(drawio_dir, node.path)
        if os.path.exists(full_path):
            return full_path

        alt_path = os.path.join(self.project_root, node.path.lstrip("./"))
        if os.path.exists(alt_path):
            return alt_path

        # Search by filename
        filename = os.path.basename(node.path)
        for root, dirs, files in os.walk(self.project_root):
            if filename in files:
                return os.path.join(root, filename)

        return None

    def _apply_changes(self) -> Optional[str]:
        """Apply the synchronization changes to the drawio file."""
        if not self.actions:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{self.drawio_file}.backup_{timestamp}"
        shutil.copy2(self.drawio_file, backup_file)

        tree = self.parser.tree
        root = self.parser.root

        changes_by_id: Dict[str, Dict[str, Any]] = {}
        for action in self.actions:
            if action.action_type == "update":
                if action.node_id not in changes_by_id:
                    changes_by_id[action.node_id] = {}
                changes_by_id[action.node_id][action.field] = action.new_value

        for elem in root.iter():
            tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag_name in ("mxCell", "object"):
                cell_id = elem.get("id")
                if cell_id in changes_by_id:
                    for attr, value in changes_by_id[cell_id].items():
                        elem.set(attr, str(value))

        tree.write(self.drawio_file, encoding="utf-8", xml_declaration=True)

        print(f"Applied {len(self.actions)} changes")
        print(f"Backup saved to: {backup_file}")

        return backup_file


def main():
    parser = argparse.ArgumentParser(
        description="Synchronize drawio diagram nodes with code files"
    )
    parser.add_argument(
        "--drawio", "-d",
        required=True,
        help="Path to the drawio file"
    )
    parser.add_argument(
        "--project-root", "-p",
        help="Project root directory"
    )
    parser.add_argument(
        "--sync",
        action="store_true",
        help="Apply changes (without this flag, runs in dry-run mode)"
    )
    parser.add_argument(
        "--update-lines",
        dest="update_lines",
        action="store_true",
        default=True,
        help="Update line numbers (default: True)"
    )
    parser.add_argument(
        "--no-update-lines",
        dest="update_lines",
        action="store_false",
        help="Skip updating line numbers"
    )
    parser.add_argument(
        "--update-labels",
        action="store_true",
        help="Update labels based on code content"
    )
    parser.add_argument(
        "--nodes",
        help="Comma-separated list of node IDs to sync (default: all)"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON report file"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--update-index",
        dest="update_index",
        action="store_true",
        default=True,
        help="Update .vscode/drawio-code-links.json after sync (default: True)"
    )
    parser.add_argument(
        "--no-index",
        action="store_false",
        dest="update_index",
        help="Skip updating the index file"
    )

    args = parser.parse_args()

    node_filter = args.nodes.split(",") if args.nodes else None

    syncer = CodeSynchronizer(
        drawio_file=args.drawio,
        project_root=args.project_root,
        dry_run=not args.sync,
        node_filter=node_filter
    )

    result = syncer.run(
        update_lines=args.update_lines,
        update_labels=args.update_labels
    )

    if args.verbose or not result.success:
        print(json.dumps({
            "success": result.success,
            "nodes_updated": result.nodes_updated,
            "actions_count": len(result.actions),
            "actions": [
                {
                    "node_id": a.node_id,
                    "node_label": a.node_label,
                    "action_type": a.action_type,
                    "field": a.field,
                    "old_value": a.old_value,
                    "new_value": a.new_value
                }
                for a in result.actions[:20]
            ],
            "errors": result.errors,
            "backup_file": result.backup_file
        }, indent=2, ensure_ascii=False))

    if result.actions:
        print(f"\nSynchronization summary:")
        print(f"  Nodes to update: {result.nodes_updated}")
        print(f"  Total changes:   {len(result.actions)}")

        if args.verbose:
            for action in result.actions:
                print(f"  - {action.node_label} ({action.node_id})")
                print(f"    {action.field}: {action.old_value} -> {action.new_value}")

    if result.errors:
        print(f"\nErrors encountered:")
        for error in result.errors:
            print(f"  - {error.get('label', error.get('node_id', 'unknown'))}: {error.get('error')}")

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump({
                "success": result.success,
                "nodes_updated": result.nodes_updated,
                "actions_count": len(result.actions),
                "errors": result.errors,
                "backup_file": result.backup_file
            }, f, indent=2, ensure_ascii=False)
        print(f"\nReport saved to: {args.output}")

    if result.success:
        if not args.sync:
            print("\n[DRY RUN] No changes made. Use --sync to apply changes.")
            sys.exit(0)

        # Tail: auto-update the code-links index
        if args.update_index and result.nodes_updated > 0:
            drawio_abs = syncer.drawio_file
            if os.path.exists(drawio_abs):
                try:
                    import subprocess
                    index_script = os.path.join(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "scripts", "index_generator.py"
                    )
                    result_proc = subprocess.run(
                        [sys.executable, index_script, "--drawio", drawio_abs],
                        capture_output=True, text=True, check=True
                    )
                    print(f"\nIndex updated: {result_proc.stdout.strip()}")
                except subprocess.CalledProcessError as e:
                    print(f"\nWarning: index update failed: {e.stderr.strip()}")
                except Exception as e:
                    print(f"\nWarning: index update failed: {e}")

        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
