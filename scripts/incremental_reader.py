#!/usr/bin/env python3
"""
Incremental Reader — Incrementally generate/update drawio diagrams from code changes.

Usage:
    # Scan project and detect changes
    python incremental_reader.py --project-root . --existing diagram.drawio --diff

    # Use git diff for engineering-grade change detection
    python incremental_reader.py --project-root . --existing diagram.drawio --git-diff

    # Apply patch to existing diagram
    python incremental_reader.py --patch patch.yaml --existing diagram.drawio --output diagram.drawio

    # Full pipeline: scan → suggest → apply
    python incremental_reader.py --project-root . --existing diagram.drawio --auto
"""

import os
import sys
import argparse
import json
import yaml
import shutil
import fnmatch
from datetime import datetime
from typing import List, Dict, Any, Optional, Set, Tuple
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.xml_parser import XmlParser, NodeInfo, EdgeInfo, DiagramData
from scripts.utils.path_utils import PathResolver, get_line_count
from scripts.layout_generator import (
    DiagramDef, NodeDef, EdgeDef, GroupDef,
    LayoutEngine, generate_xml, _dict_to_diagram, parse_input
)
from scripts.analyzer import structure_hash, content_hash, classify_change
from scripts.import_graph import build_import_graph, suggest_edges, compute_project_fingerprints, detect_changed_files
from scripts.git_diff_reader import (
    is_git_repo, check_dirty, safe_branch, commit_and_return,
    changed_files, file_diff, file_content_at_ref,
    drawio_diff, code_diff_summary, classify_change_from_diff, parse_git_diff
)


class IncrementalReader:
    """Handles incremental diagram updates from code changes."""

    def __init__(self, project_root: str, existing_drawio: Optional[str] = None):
        self.project_root = os.path.abspath(project_root)
        self.existing_drawio = existing_drawio
        self.existing_data: Optional[DiagramData] = None
        self.existing_nodes: Dict[str, NodeInfo] = {}
        self.existing_edges: List[EdgeInfo] = []
        # Fingerprint-based change detection
        self.file_fingerprints: Dict[str, Dict] = {}

        if existing_drawio and os.path.exists(existing_drawio):
            self._load_existing()

    def _load_existing(self):
        """Load existing diagram as baseline."""
        parser = XmlParser(self.existing_drawio)
        self.existing_data = parser.parse()
        for node in self.existing_data.nodes:
            self.existing_nodes[node.id] = node
        self.existing_edges = self.existing_data.edges

        # Compute structural fingerprints for all referenced files
        drawio_dir = os.path.dirname(os.path.abspath(self.existing_drawio))
        for node in self.existing_data.nodes:
            if node.path:
                full_path = os.path.normpath(os.path.join(drawio_dir, node.path))
                if os.path.exists(full_path):
                    rel_path = node.path.replace(os.sep, '/')
                    self.file_fingerprints[rel_path] = {
                        "content_hash": content_hash(full_path),
                        "structure_hash": structure_hash(full_path),
                        "lines": get_line_count(full_path),
                    }

    def scan_project(self, include_patterns: List[str] = None, exclude_patterns: List[str] = None) -> Dict[str, Any]:
        """Scan project and compare with existing diagram using fingerprint-based detection."""
        include_patterns = include_patterns or ['*.ts', '*.js', '*.py', '*.java', '*.go', '*.rs', '*.rb',
                                                '*.tsx', '*.jsx', '*.rb', '*.php', '*.c', '*.cpp', '*.h',
                                                '*.cs', '*.kt', '*.swift', '*.dart', '*.scala', '*.lua', '*.sh',
                                                'Dockerfile*', 'Makefile*', '*.yaml', '*.yml', '*.json',
                                                '*.toml', '*.cfg', '*.conf', '*.ini', '*.sql', '*.graphql']
        exclude_patterns = exclude_patterns or ['node_modules', '.git', 'dist', 'build', '__pycache__',
                                                 '*.test.*', '*.spec.*', '.venv', 'venv', 'target', 'bin', 'obj',
                                                 'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml']

        # Find all source files
        current_files = self._find_source_files(include_patterns, exclude_patterns)

        drawio_dir = os.path.dirname(os.path.abspath(self.existing_drawio)) if self.existing_drawio else self.project_root

        # Get files referenced in diagram
        diagram_files = set()
        for node in self.existing_data.nodes if self.existing_data else []:
            if node.path:
                rel = node.path.replace(os.sep, '/')
                diagram_files.add(rel)

        # Compute current fingerprints for all files
        current_fingerprints = {}
        for fp in current_files:
            rel = os.path.relpath(fp, drawio_dir).replace(os.sep, '/')
            current_fingerprints[rel] = {
                "content_hash": content_hash(fp),
                "structure_hash": structure_hash(fp),
                "lines": get_line_count(fp),
            }

        # Detect changes using fingerprint comparison
        change_map = detect_changed_files(self.file_fingerprints, current_fingerprints)

        changes: Dict[str, Any] = {
            'new_files': [],
            'deleted_files': [],
            'modified_files': [],
            'structural_changes': [],
            'unchanged_files': [],
            'orphaned_nodes': [],
            'suggested_edges': [],
        }

        for rel_path, change_type in change_map.items():
            if change_type == "new":
                if rel_path not in diagram_files:
                    fp = current_fingerprints.get(rel_path, {})
                    changes['new_files'].append({
                        'path': rel_path,
                        'type': self._infer_type_from_path(rel_path),
                        'lines': fp.get('lines', 0),
                    })
            elif change_type == "deleted":
                changes['deleted_files'].append(rel_path)
            elif change_type == "structural":
                fp = current_fingerprints.get(rel_path, {})
                old_info = self.file_fingerprints.get(rel_path, {})
                changes['modified_files'].append({
                    'path': rel_path,
                    'old_lines': old_info.get('lines', 0),
                    'new_lines': fp.get('lines', 0),
                    'change_type': 'structural',
                })
                changes['structural_changes'].append(rel_path)
            elif change_type == "cosmetic":
                # Cosmetic changes don't affect diagram structure
                pass
            else:
                changes['unchanged_files'].append(rel_path)

        # Find orphaned nodes (nodes whose files were deleted)
        deleted_set = set(changes['deleted_files'])
        for node in self.existing_data.nodes if self.existing_data else []:
            if node.path and node.path in deleted_set:
                changes['orphaned_nodes'].append({
                    'id': node.id,
                    'label': node.label,
                    'path': node.path
                })
            elif node.path and node.path not in deleted_set:
                full_path = os.path.normpath(os.path.join(drawio_dir, node.path))
                if not os.path.exists(full_path):
                    if node.path not in deleted_set:
                        changes['deleted_files'].append(node.path)
                    changes['orphaned_nodes'].append({
                        'id': node.id,
                        'label': node.label,
                        'path': node.path
                    })

        # Build import graph and suggest edges for new nodes
        if changes['new_files'] and self.existing_data:
            self._suggest_edges_from_imports(changes, drawio_dir, current_files)

        return changes

    def scan_git_diff(self, ref: str = "HEAD", include_patterns: List[str] = None,
                       exclude_patterns: List[str] = None) -> Dict[str, Any]:
        """Scan changes using git diff for engineering-grade change detection.

        Uses `git diff --name-only` to find changed files, then reads the actual
        diff content so AI can understand the SEMANTIC meaning of changes
        (not just "file changed" but "+    def divide(self, a, b):").
        """
        if not is_git_repo(self.project_root):
            return {"error": "Not a git repository. Use --diff instead of --git-diff."}

        drawio_dir = os.path.dirname(os.path.abspath(self.existing_drawio)) if self.existing_drawio else self.project_root

        changes: Dict[str, Any] = {
            'code_changes': [],
            'drawio_changes': None,
            'new_files': [],
            'deleted_files': [],
            'modified_files': [],
            'structural_changes': [],
            'cosmetic_changes': [],
            'unchanged_files': [],
            'orphaned_nodes': [],
            'suggested_edges': [],
            'code_diff_summaries': {},
        }

        all_changed = changed_files(ref, self.project_root)
        if not all_changed:
            return changes

        # Classify each changed file
        for fpath in all_changed:
            abs_path = os.path.join(self.project_root, fpath)

            # Drawio file
            if fpath.endswith(".drawio") and self.existing_drawio:
                ddiff = drawio_diff(
                    os.path.join(self.project_root, fpath),
                    ref, self.project_root
                )
                changes['drawio_changes'] = {
                    'file': fpath,
                    'added_nodes': ddiff.added_nodes,
                    'removed_nodes': ddiff.removed_nodes,
                    'modified_nodes': ddiff.modified_nodes,
                    'added_edges': ddiff.added_edges,
                    'removed_edges': ddiff.removed_edges,
                }
                continue

            # Code file
            diff_str = file_diff(fpath, ref, self.project_root)
            if diff_str is None:
                changes['deleted_files'].append(fpath)
                continue

            change_type = classify_change_from_diff(diff_str)
            summary = code_diff_summary(fpath, ref, self.project_root)

            entry = {
                'path': fpath,
                'change_type': change_type,
                'abs_path': abs_path,
                'diff_summary': summary,
            }

            if change_type == "structural":
                changes['structural_changes'].append(fpath)
                changes['modified_files'].append(entry)
            elif change_type == "cosmetic":
                changes['cosmetic_changes'].append(fpath)
            else:
                changes['unchanged_files'].append(fpath)

            if summary:
                changes['code_diff_summaries'][fpath] = summary

        # Check for orphaned nodes (diagram nodes whose file was deleted)
        if self.existing_data:
            deleted_set = set(changes['deleted_files'])
            for node in self.existing_data.nodes:
                if node.path and node.path in deleted_set:
                    changes['orphaned_nodes'].append({
                        'id': node.id,
                        'label': node.label,
                        'path': node.path
                    })

        return changes

    def _suggest_edges_from_imports(
        self, changes: Dict[str, Any], drawio_dir: str, current_files: List[str]
    ):
        """Use import graph to suggest edges between new nodes and existing nodes."""
        project_root_for_graph = self.project_root
        # Build full import graph
        all_files = list(current_files)
        graph = build_import_graph(project_root_for_graph, all_files)

        # Helper: convert drawio-relative path to project-root-relative
        def _to_project_rel(path: str) -> str:
            abs_path = os.path.normpath(os.path.join(drawio_dir, path))
            return os.path.relpath(abs_path, project_root_for_graph).replace(os.sep, '/')

        # Build existing node list from diagram (normalize to project-root relative)
        existing_pairs = []
        for node in self.existing_data.nodes if self.existing_data else []:
            if node.path:
                pr_rel = _to_project_rel(node.path)
                existing_pairs.append((node.id, pr_rel))

        # Add newly proposed nodes (they may also be drawio-relative)
        for f in changes['new_files']:
            node_id = self._make_id_from_path(f['path'])
            pr_rel = _to_project_rel(f['path'])
            existing_pairs.append((node_id, pr_rel))

        edges = suggest_edges(graph, existing_pairs)
        if edges:
            changes['suggested_edges'] = edges

    def _find_source_files(self, include_patterns: List[str], exclude_patterns: List[str]) -> List[str]:
        """Find all source files in project.
        
        Uses `git ls-files` when available (fast, .gitignore-aware),
        falls back to os.walk for non-git projects.
        """
        # Try git ls-files first
        git_files = self._scan_with_git(include_patterns, exclude_patterns)
        if git_files is not None:
            return git_files

        # Fallback: os.walk
        files = []
        for root, dirs, filenames in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, ex) for ex in exclude_patterns)]
            for filename in filenames:
                if any(fnmatch.fnmatch(filename, p) for p in include_patterns):
                    if not any(fnmatch.fnmatch(filename, ex) for ex in exclude_patterns):
                        files.append(os.path.join(root, filename))
        return files

    def _scan_with_git(self, include_patterns: List[str], exclude_patterns: List[str]) -> Optional[List[str]]:
        """Use git ls-files for fast, .gitignore-aware scanning. Returns None if not a git repo."""
        try:
            import subprocess
            result = subprocess.run(
                ["git", "ls-files", "-z"],
                capture_output=True, text=False, timeout=30,
                cwd=self.project_root
            )
            if result.returncode != 0:
                return None
            # Split on null bytes, decode
            all_files = result.stdout.decode("utf-8", errors="replace").split("\0")
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

        matched = []
        for fpath in all_files:
            if not fpath.strip():
                continue
            # Check include patterns
            if not any(fnmatch.fnmatch(fpath, p) for p in include_patterns):
                # Also check basename-only patterns against full path components
                basename = os.path.basename(fpath)
                if not any(fnmatch.fnmatch(basename, p) for p in include_patterns):
                    continue
            # Check exclude patterns
            if any(fnmatch.fnmatch(fpath, ex) for ex in exclude_patterns):
                continue
            if any(part in fpath.split("/") for part in exclude_patterns if "/" not in part):
                continue
            matched.append(os.path.join(self.project_root, fpath))

        return matched

    def _infer_type_from_path(self, file_path: str) -> str:
        """Infer node type from file path."""
        path_lower = file_path.lower()
        basename = os.path.basename(file_path).lower()
        # Non-code files
        if basename.startswith("dockerfile"):
            return 'infrastructure'
        if basename.startswith("makefile"):
            return 'infrastructure'
        if basename in ('.github/workflows', '.gitlab-ci.yml', '.circleci/config.yml', 'Jenkinsfile'):
            return 'infrastructure'
        if file_path.endswith(('.yml', '.yaml')):
            if 'workflow' in path_lower or 'ci' in path_lower:
                return 'infrastructure'
            return 'config'
        if file_path.endswith(('.toml', '.cfg', '.conf', '.ini')):
            return 'config'
        if file_path.endswith('.sql'):
            return 'data'
        if file_path.endswith('.graphql'):
            return 'data'
        # Code files
        if any(x in path_lower for x in ['controller', 'ctrl', 'handler', 'route']):
            return 'controller'
        elif any(x in path_lower for x in ['service', 'usecase', 'biz']):
            return 'service'
        elif any(x in path_lower for x in ['model', 'entity', 'schema', 'dto']):
            return 'data'
        elif any(x in path_lower for x in ['middleware', 'infra', 'util', 'helper']):
            return 'infrastructure'
        elif any(x in path_lower for x in ['config', 'main', 'index', 'app']):
            return 'entry'
        elif any(x in path_lower for x in ['external', 'api', 'client', 'third']):
            return 'external'
        return 'service'

    def generate_patch_yaml(self, changes: Dict[str, Any]) -> str:
        """Generate patch YAML from changes."""
        patch = {
            'action': 'patch',
            'existing': self.existing_drawio,
        }

        # Add nodes for new files
        if changes['new_files']:
            patch['add_nodes'] = []
            for f in changes['new_files']:
                node_id = self._make_id_from_path(f['path'])
                group = self._infer_group_from_path(f['path'])
                patch['add_nodes'].append({
                    'id': node_id,
                    'label': self._make_label_from_path(f['path']),
                    'type': f['type'],
                    'group': group,
                    'path': f['path'],
                    'lines': [0, max(0, f['lines'] - 1)]
                })

        # Delete nodes for deleted files
        if changes['deleted_files']:
            patch['delete_nodes'] = []
            for node in self.existing_data.nodes if self.existing_data else []:
                if node.path and node.path in changes['deleted_files']:
                    patch['delete_nodes'].append({'id': node.id})

        # Update nodes for modified files
        if changes['modified_files']:
            patch['update_nodes'] = []
            for f in changes['modified_files']:
                for node in self.existing_data.nodes if self.existing_data else []:
                    if node.path == f['path']:
                        patch['update_nodes'].append({
                            'id': node.id,
                            'lines': [0, max(0, f['new_lines'] - 1)]
                        })

        # Mark orphaned nodes
        if changes['orphaned_nodes']:
            patch['update_nodes'] = patch.get('update_nodes', [])
            for orphan in changes['orphaned_nodes']:
                patch['update_nodes'].append({
                    'id': orphan['id'],
                    'label': f"⚠ {orphan['label']} (DELETED)"
                })

        patch['layout'] = {
            'algorithm': 'preserve',
            'preserve_existing': True
        }

        return yaml.dump(patch, allow_unicode=True, sort_keys=False)

    def _make_id_from_path(self, path: str) -> str:
        """Create a valid node ID from file path."""
        name = os.path.splitext(os.path.basename(path))[0]
        # Remove invalid chars
        name = ''.join(c if c.isalnum() or c == '_' else '_' for c in name)
        # Ensure starts with letter
        if name and not name[0].isalpha():
            name = 'n_' + name
        return name

    def _make_label_from_path(self, path: str) -> str:
        """Create a label from file path."""
        name = os.path.splitext(os.path.basename(path))[0]
        # Convert camelCase/PascalCase to words
        import re
        name = re.sub('([A-Z])', r' \1', name).strip()
        return name

    def _infer_group_from_path(self, path: str) -> str:
        """Infer group name from file path."""
        parts = path.split('/')
        if len(parts) >= 2:
            dir_name = parts[-2]
            if dir_name in ('src', 'lib', 'app'):
                return parts[-3] if len(parts) >= 3 else 'src'
            return dir_name
        return 'main'

    def apply_patch(self, patch_yaml_path: str, output_path: str) -> bool:
        """Apply patch YAML to existing diagram."""
        # Parse patch
        with open(patch_yaml_path, 'r', encoding='utf-8') as f:
            patch = yaml.safe_load(f)

        # Build diagram definition from existing + patch
        diagram_def = self._build_diagram_def_from_patch(patch)

        # Compute layout
        engine = LayoutEngine(diagram_def)
        engine.compute_layout()

        # Validate
        from scripts.utils.layout_utils import LayoutAnalyzer
        analyzer = LayoutAnalyzer(
            nodes=diagram_def.nodes,
            edges=diagram_def.edges,
            page_width=diagram_def.page_width,
            page_height=diagram_def.page_height
        )
        report = analyzer.analyze()

        # Auto-fix overlaps (3 rounds)
        for _ in range(3):
            if not report.overlaps:
                break
            engine._fix_overlaps()
            report = analyzer.analyze()

        # Backup existing
        if self.existing_drawio and os.path.exists(self.existing_drawio):
            backup = f"{self.existing_drawio}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(self.existing_drawio, backup)

        # Generate and write XML
        xml = generate_xml(diagram_def)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(xml)

        print(f"Applied patch: {output_path}")
        print(f"  Added nodes: {len(patch.get('add_nodes', []))}")
        print(f"  Deleted nodes: {len(patch.get('delete_nodes', []))}")
        print(f"  Updated nodes: {len(patch.get('update_nodes', []))}")
        if report.overlaps:
            print(f"  Warning: {len(report.overlaps)} overlaps remain")

        return True

    def _build_diagram_def_from_patch(self, patch: Dict[str, Any]) -> DiagramDef:
        """Build diagram definition from existing + patch."""
        diagram_def = DiagramDef()

        # Copy existing nodes (preserving coordinates)
        existing_node_ids = set()
        if self.existing_data:
            for node in self.existing_data.nodes:
                existing_node_ids.add(node.id)
                n = NodeDef(
                    id=node.id,
                    label=node.label,
                    node_type='service',  # Will infer from style
                    group=None,
                    path=node.path or '',
                    lines=[node.start_line or 0, node.end_line or 0],
                    x=node.x,
                    y=node.y,
                    width=node.width or 140,
                    height=node.height or 60
                )
                # Infer type from style
                if 'fillColor=#e6f7ff' in (node.style or ''):
                    n.node_type = 'service'
                elif 'fillColor=#f6ffed' in (node.style or ''):
                    n.node_type = 'data'
                elif 'fillColor=#fff7e6' in (node.style or ''):
                    n.node_type = 'entry'
                elif 'fillColor=#fff1f0' in (node.style or ''):
                    n.node_type = 'external'
                elif 'fillColor=#f9f0ff' in (node.style or ''):
                    n.node_type = 'controller'
                elif 'fillColor=#f0f5ff' in (node.style or ''):
                    n.node_type = 'infrastructure'
                diagram_def.nodes.append(n)

            # Copy existing edges
            for edge in self.existing_edges:
                diagram_def.edges.append(EdgeDef(
                    source_id=edge.source_id,
                    target_id=edge.target_id,
                    label=edge.label or '',
                    style='solid'
                ))

        # Apply delete_nodes
        delete_ids = {n['id'] for n in patch.get('delete_nodes', [])}
        diagram_def.nodes = [n for n in diagram_def.nodes if n.id not in delete_ids]
        diagram_def.edges = [e for e in diagram_def.edges if e.source_id not in delete_ids and e.target_id not in delete_ids]

        # Apply update_nodes
        update_map = {n['id']: n for n in patch.get('update_nodes', [])}
        for node in diagram_def.nodes:
            if node.id in update_map:
                update = update_map[node.id]
                if 'label' in update:
                    node.label = update['label']
                if 'lines' in update:
                    node.lines = update['lines']
                if 'type' in update:
                    node.node_type = update['type']
                if 'group' in update:
                    node.group = update['group']
                if 'path' in update:
                    node.path = update['path']

        # Apply add_nodes
        existing_ids = {n.id for n in diagram_def.nodes}
        for add_node in patch.get('add_nodes', []):
            # Check for duplicate ID, retry with suffix
            node_id = add_node['id']
            while node_id in existing_ids:
                node_id = f"{node_id}_1"
            existing_ids.add(node_id)
            diagram_def.nodes.append(NodeDef(
                id=node_id,
                label=add_node['label'],
                node_type=add_node.get('type', 'service'),
                group=add_node.get('group'),
                path=add_node.get('path', ''),
                lines=add_node.get('lines', [0, 0])
            ))

        # Apply delete_edges
        delete_edge_set = set()
        for de in patch.get('delete_edges', []):
            delete_edge_set.add((de['from'], de['to']))
        diagram_def.edges = [e for e in diagram_def.edges if (e.source_id, e.target_id) not in delete_edge_set]

        # Apply add_edges
        for add_edge in patch.get('add_edges', []):
            diagram_def.edges.append(EdgeDef(
                source_id=add_edge['from'],
                target_id=add_edge['to'],
                label=add_edge.get('label', ''),
                path=add_edge.get('path', ''),
                lines=add_edge.get('lines', [0, 0]),
                style=add_edge.get('style', 'solid')
            ))

        # Layout settings
        layout = patch.get('layout', {})
        diagram_def.layout_algorithm = layout.get('algorithm', 'preserve')
        diagram_def.layout_direction = layout.get('direction', 'top-to-bottom')
        diagram_def.preserve_existing = layout.get('preserve_existing', True)

        return diagram_def


def _update_index(drawio_path: str) -> None:
    """Call index_generator to update .vscode/drawio-code-links.json."""
    try:
        import subprocess
        index_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "scripts", "index_generator.py"
        )
        result = subprocess.run(
            [sys.executable, index_script, "--drawio", drawio_path],
            capture_output=True, text=True, check=True
        )
        print(f"Index updated: {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        print(f"Warning: index update failed: {e.stderr.strip()}")
    except Exception as e:
        print(f"Warning: index update failed: {e}")


def main():
    parser = argparse.ArgumentParser(description='Incremental diagram reader')
    parser.add_argument('--project-root', '-p', default='.', help='Project root directory')
    parser.add_argument('--existing', '-e', help='Existing .drawio file')
    parser.add_argument('--diff', action='store_true', help='Detect changes and output report')
    parser.add_argument('--git-diff', action='store_true', help='Detect changes via git diff (engineering-grade)')
    parser.add_argument('--git-ref', default='HEAD', help='Git ref to diff against (default: HEAD)')
    parser.add_argument('--no-branch', action='store_true', help='Skip auto-branch creation for write operations')
    parser.add_argument('--patch', help='Apply patch YAML file')
    parser.add_argument('--output', '-o', help='Output .drawio file')
    parser.add_argument('--auto', action='store_true', help='Auto mode: scan + suggest + apply')
    parser.add_argument('--include', nargs='+', help='Include patterns')
    parser.add_argument('--exclude', nargs='+', help='Exclude patterns')
    parser.add_argument(
        "--update-index",
        dest="update_index",
        action="store_true",
        default=True,
        help="Update .vscode/drawio-code-links.json after patch (default: True)"
    )
    parser.add_argument(
        "--no-index",
        action="store_false",
        dest="update_index",
        help="Skip updating the index file"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    args = parser.parse_args()

    reader = IncrementalReader(args.project_root, args.existing)

    if args.diff:
        changes = reader.scan_project(args.include, args.exclude)
        print("# Change Report")
        print(yaml.dump(changes, allow_unicode=True, sort_keys=False))

        # Also generate suggested patch
        print("\n# Suggested Patch")
        print(reader.generate_patch_yaml(changes))

    elif args.git_diff:
        from scripts.git_diff_reader import is_git_repo
        if not is_git_repo(args.project_root):
            print("Error: Not a git repository. Use --diff instead.", file=sys.stderr)
            sys.exit(1)
        changes = reader.scan_git_diff(ref=args.git_ref)
        print("# Git Diff Change Report")
        print(yaml.dump(changes, allow_unicode=True, sort_keys=False))
        if args.verbose and changes.get('code_diff_summaries'):
            print("\n# Code Diff Summaries (for AI semantic understanding)")
            for fpath, summary in changes['code_diff_summaries'].items():
                print(summary)

    elif args.patch:
        output = args.output or args.existing
        if not output:
            print("Error: Specify --output or --existing", file=sys.stderr)
            sys.exit(1)
        reader.apply_patch(args.patch, output)
        if args.update_index and output:
            _update_index(output)

    elif args.auto:
        changes = reader.scan_project(args.include, args.exclude)
        patch_yaml = reader.generate_patch_yaml(changes)

        # Write temp patch
        temp_patch = '/tmp/drawio_auto_patch.yaml'
        with open(temp_patch, 'w') as f:
            f.write(patch_yaml)

        output = args.output or args.existing
        reader.apply_patch(temp_patch, output)
        if args.update_index and output:
            _update_index(output)

    else:
        print("Use --diff to detect changes, --patch to apply, or --auto for full pipeline")


if __name__ == '__main__':
    main()
