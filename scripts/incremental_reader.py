#!/usr/bin/env python3
"""
Incremental Reader — Detect code changes and generate patch YAML for diagram updates.

Usage:
    # Auto-detect git or fallback to file scan
    python incremental_reader.py --project-root . --existing arch.drawio --scan

    # Force git diff mode
    python incremental_reader.py --project-root . --existing arch.drawio --git-diff

    # Output to file
    python incremental_reader.py --project-root . --existing arch.drawio --scan --output patch.yaml
"""

import os
import sys
import re
import argparse
import json
import yaml
import fnmatch
import hashlib
from typing import List, Dict, Any, Optional
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.xml_parser import XmlParser, NodeInfo, EdgeInfo, DiagramData
from scripts.utils.path_utils import get_line_count
from scripts.import_graph import build_import_graph, suggest_edges
from scripts.analyzer import extract_struct_fields
from scripts.git_diff_reader import (
    is_git_repo, changed_files, untracked_files, file_diff,
    drawio_diff, code_diff_summary, classify_change_from_diff,
)


CACHE_FILE = ".drawio-scan-cache.json"


class IncrementalReader:
    """Detects code changes and outputs patch YAML for diagram updates.

    Primary detection uses git diff (fast, precise, O(changes)).
    Falls back to content-hash fingerprint cache for non-git projects.
    """

    def __init__(self, project_root: str, existing_drawio: Optional[str] = None):
        self.project_root = os.path.abspath(project_root)
        self.existing_drawio = existing_drawio
        self.existing_data: Optional[DiagramData] = None
        self.existing_nodes: Dict[str, NodeInfo] = {}
        self.existing_edges: List[EdgeInfo] = []

        if existing_drawio and os.path.exists(existing_drawio):
            self._load_existing()

    def _load_existing(self):
        parser = XmlParser(self.existing_drawio)
        self.existing_data = parser.parse()
        drawio_dir = os.path.dirname(os.path.abspath(self.existing_drawio))
        for node in self.existing_data.nodes:
            self.existing_nodes[node.id] = node
            # Normalize drawio-XML path → project-root-relative path
            if node.path:
                # The XML path includes _fix_hediet_path compensation (../).
                # Resolve relative to drawio dir, then relativize against project root.
                abs_path = os.path.normpath(os.path.join(drawio_dir, node.path))
                node.path = os.path.relpath(abs_path, self.project_root).replace(os.sep, '/')
        self.existing_edges = self.existing_data.edges

    # ── Scan entry point ─────────────────────────────────────────────

    def scan(self, ref: str = "HEAD", include: Optional[List[str]] = None,
             exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        has_existing = bool(self.existing_data and self.existing_data.nodes)

        # First run (no existing diagram): use git ls-files or os.walk to list all sources
        if not has_existing:
            return self._scan_first_run(include, exclude)

        # Incremental update: git-diff is primary, fingerprint is fallback
        if is_git_repo(self.project_root):
            return self._scan_git(ref)
        return self._scan_fallback(include, exclude)

    # ── First run: list all source files as new ──────────────────────

    def _scan_first_run(self, include: Optional[List[str]] = None,
                        exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        include = include or self._default_includes()
        exclude = exclude or self._default_excludes()
        files = self._find_source_files(include, exclude)
        drawio_dir = os.path.dirname(os.path.abspath(self.existing_drawio)) if self.existing_drawio else self.project_root

        changes: Dict[str, Any] = {
            'new_files': [], 'deleted_files': [], 'modified_files': [],
            'structural_changes': [], 'unchanged_files': [],
            'orphaned_nodes': [], 'suggested_edges': [],
        }

        for fp in files:
            rel = os.path.relpath(fp, drawio_dir).replace(os.sep, '/')
            changes['new_files'].append({
                'path': rel, 'type': self._infer_type_from_path(rel),
                'lines': get_line_count(fp),
            })

        self._enrich_struct_fields(changes, drawio_dir)
        self._detect_l1_dependencies(changes, drawio_dir)
        self._suggest_edges(changes, drawio_dir, files)
        return changes

    def _scan_git(self, ref: str = "HEAD") -> Dict[str, Any]:
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

        # Merge tracked changes + untracked files
        all_changed = list(set(changed_files(ref, self.project_root) + untracked_files(self.project_root)))
        if not all_changed:
            return changes

        for fpath in all_changed:
            abs_path = os.path.join(self.project_root, fpath)

            if fpath.endswith(".drawio") and self.existing_drawio:
                ddiff = drawio_diff(os.path.join(self.project_root, fpath), ref, self.project_root)
                changes['drawio_changes'] = {
                    'file': fpath,
                    'added_nodes': ddiff.added_nodes,
                    'removed_nodes': ddiff.removed_nodes,
                    'modified_nodes': ddiff.modified_nodes,
                    'added_edges': ddiff.added_edges,
                    'removed_edges': ddiff.removed_edges,
                }
                continue

            file_exists = os.path.isfile(abs_path)
            diff_str = file_diff(fpath, ref, self.project_root)
            if diff_str is None and not file_exists:
                changes['deleted_files'].append(fpath)
                continue
            elif diff_str is None and file_exists:
                changes['new_files'].append({
                    'path': fpath, 'type': self._infer_type_from_path(fpath),
                    'lines': get_line_count(abs_path),
                })
                continue

            change_type = classify_change_from_diff(diff_str)
            summary = code_diff_summary(fpath, ref, self.project_root)

            entry = {'path': fpath, 'change_type': change_type, 'abs_path': abs_path,
                      'new_lines': get_line_count(abs_path), 'diff_summary': summary}

            if change_type == "structural":
                changes['structural_changes'].append(fpath)
                changes['modified_files'].append(entry)
            elif change_type == "cosmetic":
                changes['cosmetic_changes'].append(fpath)
            else:
                changes['unchanged_files'].append(fpath)

            if summary:
                changes['code_diff_summaries'][fpath] = summary

        self._detect_orphans(changes)
        self._enrich_struct_fields(changes, drawio_dir)
        source_files = [os.path.join(self.project_root, p) for p in all_changed
                        if os.path.isfile(os.path.join(self.project_root, p))]
        self._detect_l1_dependencies(changes, drawio_dir)
        self._suggest_edges(changes, drawio_dir, source_files)
        return changes

    # ── Fingerprint fallback (non-git) ───────────────────────────────

    def _scan_fallback(self, include: Optional[List[str]] = None,
                       exclude: Optional[List[str]] = None) -> Dict[str, Any]:
        include = include or self._default_includes()
        exclude = exclude or self._default_excludes()

        current_files = self._find_source_files(include, exclude)
        drawio_dir = os.path.dirname(os.path.abspath(self.existing_drawio)) if self.existing_drawio else self.project_root

        old_cache = self._load_cache()
        new_cache: Dict[str, str] = {}
        changes: Dict[str, Any] = {
            'new_files': [], 'deleted_files': [], 'modified_files': [],
            'structural_changes': [], 'unchanged_files': [],
            'orphaned_nodes': [], 'suggested_edges': [],
        }

        for fp in current_files:
            rel = os.path.relpath(fp, drawio_dir).replace(os.sep, '/')
            h = self._file_hash(fp)
            new_cache[rel] = h
            if rel not in old_cache:
                changes['new_files'].append({'path': rel, 'type': self._infer_type_from_path(rel), 'lines': get_line_count(fp)})
            elif old_cache[rel] != h:
                changes['modified_files'].append({'path': rel, 'old_lines': 0, 'new_lines': get_line_count(fp), 'change_type': 'structural'})
                changes['structural_changes'].append(rel)
            else:
                changes['unchanged_files'].append(rel)

        for rel in old_cache:
            if rel not in new_cache:
                changes['deleted_files'].append(rel)

        self._detect_orphans(changes)
        self._enrich_struct_fields(changes, drawio_dir)
        self._detect_l1_dependencies(changes, drawio_dir)
        self._save_cache(new_cache)
        self._suggest_edges(changes, drawio_dir, current_files)
        return changes

    def _file_hash(self, file_path: str) -> str:
        try:
            with open(file_path, 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()[:16]
        except OSError:
            return ""

    def _load_cache(self) -> Dict[str, str]:
        cache_path = os.path.join(self.project_root, CACHE_FILE)
        if os.path.exists(cache_path):
            try:
                with open(cache_path) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_cache(self, cache: Dict[str, str]):
        cache_path = os.path.join(self.project_root, CACHE_FILE)
        try:
            with open(cache_path, 'w') as f:
                json.dump(cache, f, indent=2)
        except OSError:
            pass

    # ── Shared helpers ───────────────────────────────────────────────

    def _detect_orphans(self, changes: Dict[str, Any]):
        if not self.existing_data:
            return
        deleted_set = set(changes.get('deleted_files', []))
        for node in self.existing_data.nodes:
            if node.path and node.path in deleted_set:
                changes.setdefault('orphaned_nodes', []).append({
                    'id': node.id, 'label': node.label, 'path': node.path
                })

    def _suggest_edges(self, changes: Dict[str, Any], drawio_dir: str, source_files: List[str]):
        if not changes.get('new_files'):
            return
        project_root = self.project_root
        graph = build_import_graph(project_root, source_files)

        def to_project_rel(path: str) -> str:
            abs_path = os.path.normpath(os.path.join(drawio_dir, path))
            return os.path.relpath(abs_path, project_root).replace(os.sep, '/')

        pairs = []
        for node in self.existing_data.nodes if self.existing_data else []:
            if node.path:
                pairs.append((node.id, to_project_rel(node.path)))
        for f in changes['new_files']:
            pairs.append((self._make_id_from_path(f['path']), to_project_rel(f['path'])))

        edges = suggest_edges(graph, pairs)
        if edges:
            changes['suggested_edges'] = edges

    def _enrich_struct_fields(self, changes: Dict[str, Any], drawio_dir: str):
        """Attach struct/class field info to new_file entries."""
        for f in changes.get('new_files', []):
            abs_path = os.path.normpath(os.path.join(drawio_dir, f['path']))
            if not os.path.isfile(abs_path):
                continue
            structs = extract_struct_fields(abs_path)
            if not structs:
                continue
            # Flatten all structs' fields into members list
            members = []
            for struct_name, sfields in structs.items():
                if sfields:
                    members.append(f"── {struct_name} ──")
                    for sf in sfields:
                        parts = [sf.name]
                        if sf.type_name:
                            parts.append(sf.type_name)
                        members.append("  " + ": ".join(parts))
            if members:
                f['members'] = members
                if f.get('type') in ('service', 'infrastructure'):
                    f['type'] = 'data'

    def _detect_l1_dependencies(self, changes: Dict[str, Any], drawio_dir: str):
        """Scan files for external dependencies (system libs, Docker base, toolchain) and add L1 external nodes."""
        externals: Dict[str, Dict] = {}
        include_pattern = re.compile(r'#include\s+<([^>]+)>')

        for f in changes.get('new_files', []):
            abs_path = os.path.normpath(os.path.join(drawio_dir, f['path']))
            if not os.path.isfile(abs_path):
                continue

            # C/C++ system includes
            if f['path'].endswith(('.c', '.cpp', '.h', '.hpp')):
                try:
                    with open(abs_path, 'r', errors='replace') as fh:
                        for line in fh:
                            m = include_pattern.search(line)
                            if m:
                                header = m.group(1)
                                # Skip project-relative includes
                                if header.startswith('"'):
                                    continue
                                parts = header.split('/')
                                if len(parts) >= 2 and parts[0] not in ('sys', 'linux', 'asm'):
                                    continue
                                sys_name = parts[0]
                                if sys_name not in externals and sys_name not in ('sys', 'linux', 'asm', 'machine', 'xen'):
                                    externals[sys_name] = {
                                        'path': f'<{header}>',
                                        'label': sys_name,
                                        'type': 'external',
                                        'group': 'system',
                                    }
                except Exception:
                    pass

            # Dockerfile
            if os.path.basename(abs_path).startswith('Dockerfile'):
                try:
                    with open(abs_path, 'r', errors='replace') as fh:
                        for line in fh:
                            m = re.match(r'FROM\s+(\S+)', line)
                            if m:
                                image = m.group(1).split(':')[0]
                                if image not in externals:
                                    externals[image] = {
                                        'path': '',
                                        'label': image,
                                        'type': 'external',
                                        'group': 'runtime',
                                    }
                except Exception:
                    pass

        if externals:
            changes['l1_externals'] = list(externals.values())

    def _find_source_files(self, include: List[str], exclude: List[str]) -> List[str]:
        try:
            import subprocess
            result = subprocess.run(["git", "ls-files", "-z"], capture_output=True, text=False,
                                    timeout=30, cwd=self.project_root)
            if result.returncode == 0:
                files = result.stdout.decode("utf-8", errors="replace").split("\0")
                matched = []
                for fpath in files:
                    if not fpath.strip():
                        continue
                    if not any(fnmatch.fnmatch(fpath, p) for p in include):
                        base = os.path.basename(fpath)
                        if not any(fnmatch.fnmatch(base, p) for p in include):
                            continue
                    if any(fnmatch.fnmatch(fpath, ex) for ex in exclude):
                        continue
                    if any(part in fpath.split("/") for part in exclude if "/" not in part):
                        continue
                    matched.append(os.path.join(self.project_root, fpath))
                return matched
        except Exception:
            pass

        files = []
        for root, dirs, filenames in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if not any(fnmatch.fnmatch(d, ex) for ex in exclude)]
            for fn in filenames:
                if any(fnmatch.fnmatch(fn, p) for p in include):
                    if not any(fnmatch.fnmatch(fn, ex) for ex in exclude):
                        files.append(os.path.join(root, fn))
        return files

    def _default_includes(self) -> List[str]:
        return ['*.ts', '*.js', '*.py', '*.java', '*.go', '*.rs', '*.rb',
                '*.tsx', '*.jsx', '*.php', '*.c', '*.cpp', '*.h',
                '*.cs', '*.kt', '*.swift', '*.dart', '*.scala', '*.lua', '*.sh',
                'Dockerfile*', 'Makefile*', '*.yaml', '*.yml', '*.json',
                '*.toml', '*.cfg', '*.conf', '*.ini', '*.sql', '*.graphql']

    def _default_excludes(self) -> List[str]:
        return ['node_modules', '.git', 'dist', 'build', '__pycache__',
                '*.test.*', '*.spec.*', '.venv', 'venv', 'target', 'bin', 'obj',
                'package-lock.json', 'yarn.lock', 'pnpm-lock.yaml']

    def _infer_type_from_path(self, file_path: str) -> str:
        path_lower = file_path.lower()
        basename = os.path.basename(file_path).lower()
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

    def generate_patch_yaml(self, changes: Dict[str, Any], level: str = "L4") -> str:
        """Generate patch YAML filtered by architecture level.
        
        Args:
            changes: Scan results dict
            level: L1 (system context), L4 (data structs). L2 is AI-authored.
        """
        patch: Dict[str, Any] = {'action': 'patch', 'existing': self.existing_drawio}

        if level == "L1":
            self._build_l1_patch(changes, patch)
        elif level == "L4":
            self._build_l4_patch(changes, patch)

        self._apply_layout(patch)
        return yaml.dump(patch, allow_unicode=True, sort_keys=False)

    def _build_l1_patch(self, changes: Dict[str, Any], patch: Dict[str, Any]):
        """System context: project node + external dependencies."""
        project_name = os.path.basename(self.project_root.rstrip('/'))
        patch.setdefault('add_nodes', [])
        # Central project node (always present)
        patch['add_nodes'].append({
            'id': 'project',
            'label': project_name,
            'type': 'entry',
            'group': 'system',
            'path': '',
            'lines': [0, 0],
        })
        if not changes.get('l1_externals'):
            return
        # External nodes
        for ext in changes['l1_externals']:
            eid = ext['label'].replace('-', '_').replace('.', '_')
            patch['add_nodes'].append({
                'id': eid,
                'label': ext['label'],
                'type': 'external',
                'group': ext.get('group', 'system'),
                'path': '',
                'lines': [0, 0],
            })
        # Connect project → external
        for ext in changes['l1_externals']:
            eid = ext['label'].replace('-', '_').replace('.', '_')
            patch.setdefault('add_edges', []).append({
                'from': 'project', 'to': eid,
                'label': 'depends on', 'style': 'dashed',
            })

    def _build_l2_patch(self, changes: Dict[str, Any], patch: Dict[str, Any]):
        """Module architecture: source file-only nodes, no struct fields, no edges (AI draws them)."""
        if changes.get('new_files'):
            patch['add_nodes'] = []
            for f in changes['new_files']:
                patch['add_nodes'].append({
                    'id': self._make_id_from_path(f['path']),
                    'label': self._make_label_from_path(f['path']),
                    'type': f['type'],
                    'group': self._infer_group_from_path(f['path']),
                    'path': f['path'],
                    'lines': [0, max(0, f['lines'] - 1)],
                })

        if changes.get('deleted_files') and self.existing_data:
            patch['delete_nodes'] = []
            for node in self.existing_data.nodes:
                if node.path and node.path in changes['deleted_files']:
                    patch['delete_nodes'].append({'id': node.id})

        if changes.get('modified_files') and self.existing_data:
            patch['update_nodes'] = []
            for f in changes['modified_files']:
                for node in self.existing_data.nodes:
                    if node.path == f['path']:
                        patch['update_nodes'].append({
                            'id': node.id, 'lines': [0, max(0, f['new_lines'] - 1)]
                        })

        if changes.get('orphaned_nodes'):
            patch['update_nodes'] = patch.get('update_nodes', [])
            for orphan in changes['orphaned_nodes']:
                patch['update_nodes'].append({
                    'id': orphan['id'], 'label': f"⚠ {orphan['label']} (DELETED)"
                })

    def _build_l4_patch(self, changes: Dict[str, Any], patch: Dict[str, Any]):
        """Data structures: only struct/class nodes with field members."""
        structured = [f for f in changes.get('new_files', []) if f.get('members')]
        if not structured:
            return

        patch.setdefault('add_nodes', [])
        for f in structured:
            patch['add_nodes'].append({
                'id': self._make_id_from_path(f['path']),
                'label': self._make_label_from_path(f['path']),
                'type': 'data',
                'group': f.get('group', self._infer_group_from_path(f['path'])),
                'path': f['path'],
                'lines': [0, max(0, f['lines'] - 1)],
                'members': f['members'],
                'container': True,
            })

        # If existing diagram, update struct nodes whose file changed
        if changes.get('modified_files') and self.existing_data:
            fpaths_changed = set(f['path'] for f in changes['modified_files'])
            patch['update_nodes'] = patch.get('update_nodes', [])
            for node in self.existing_data.nodes:
                if node.path in fpaths_changed and node.path in {s['path'] for s in structured}:
                    new_fields = next((s['members'] for s in structured if s['path'] == node.path), None)
                    if new_fields:
                        patch['update_nodes'].append({
                            'id': node.id,
                            'members': new_fields,
                        })

    def _apply_layout(self, patch: Dict[str, Any]):
        has_existing = bool(self.existing_data and self.existing_data.nodes)
        if patch.get('add_nodes'):
            patch['layout'] = {
                'algorithm': 'preserve', 'preserve_existing': True,
            } if has_existing else {
                'algorithm': 'layered', 'direction': 'top-to-bottom',
            }
        else:
            patch['layout'] = {}

    def _make_id_from_path(self, path: str) -> str:
        parts = path.replace(os.sep, '/').split('/')
        stem = os.path.splitext(parts[-1])[0]
        ext = os.path.splitext(parts[-1])[1].lstrip('.')
        dir_prefix = '_'.join(p for p in parts[:-1] if p and p != '.')
        name = f"{stem}_{ext}" if ext else stem
        if dir_prefix:
            name = f"{dir_prefix}_{name}"
        name = ''.join(c if c.isalnum() or c == '_' else '_' for c in name)
        if name and not name[0].isalpha():
            name = 'n_' + name
        return name

    def _make_label_from_path(self, path: str) -> str:
        import re
        name = os.path.splitext(os.path.basename(path))[0]
        return re.sub('([A-Z])', r' \1', name).strip()

    def _infer_group_from_path(self, path: str) -> str:
        parts = path.split('/')
        if len(parts) >= 2:
            dir_name = parts[-2]
            if dir_name in ('src', 'lib', 'app'):
                return parts[-3] if len(parts) >= 3 else 'src'
            return dir_name
        return 'main'


def main():
    parser = argparse.ArgumentParser(description='Incremental diagram reader')
    parser.add_argument('--project-root', '-p', default='.', help='Project root directory')
    parser.add_argument('--existing', '-e', help='Existing .drawio file')
    parser.add_argument('--scan', action='store_true', help='Scan changes (auto git or fallback)')
    parser.add_argument('--git-diff', action='store_true', help='Force git diff mode')
    parser.add_argument('--git-ref', default='HEAD', help='Git ref to diff against')
    parser.add_argument('--output', '-o', help='Output path (.yaml report or .drawio with --generate)')
    parser.add_argument('--level', choices=['L1', 'L2', 'L4'], default=None,
                        help='Filter report to level (L1=externals, L2=modules, L4=structs)')
    parser.add_argument('--generate', action='store_true',
                        help='Generate .drawio (L4: struct nodes, L1: context nodes). L2 is AI-only.')
    parser.add_argument('--include', nargs='+', help='Include patterns (fallback only)')
    parser.add_argument('--exclude', nargs='+', help='Exclude patterns (fallback only)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    if args.generate and not args.level:
        print("Error: --generate requires --level (L1 or L4). L2 is AI-authored, not auto-generated.",
              file=sys.stderr)
        sys.exit(1)
    if args.generate and args.level == "L2":
        print("Error: L2 cannot be auto-generated. AI writes L2 YAML from the scan report.",
              file=sys.stderr)
        sys.exit(1)
    if not args.scan and not args.git_diff:
        print("Use --scan to detect changes, or --git-diff for git-only mode")
        parser.print_help()
        return

    reader = IncrementalReader(args.project_root, args.existing)
    if args.git_diff:
        if not is_git_repo(args.project_root):
            print("Error: Not a git repository.", file=sys.stderr)
            sys.exit(1)
        changes = reader._scan_git(ref=args.git_ref)
    else:
        changes = reader.scan(ref=args.git_ref, include=args.include, exclude=args.exclude)

    if args.generate and args.output and args.level in ("L4", "L1"):
        # Auto-generate .drawio for L4 or L1
        yaml_out = reader.generate_patch_yaml(changes, level=args.level)
        _invoke_generator(yaml_out, args.output)
    else:
        # Write scan report for AI
        report = _build_ai_report(changes, args.level)
        yaml_text = yaml.dump(report, allow_unicode=True, sort_keys=False)
        if args.output:
            with open(args.output, 'w') as f:
                f.write("# Scan Report (for AI reference)\n")
                f.write(yaml_text)
            print(f"Written: {args.output}")
        else:
            print("# Scan Report (for AI reference)")
            print(yaml_text)


def _build_ai_report(changes: Dict[str, Any], level: Optional[str]) -> Dict[str, Any]:
    """Build a clean scan report for AI consumption, filtered by level."""
    report: Dict[str, Any] = {}

    if level is None or level == "L2":
        report['files'] = _format_file_list(changes.get('new_files', []))
        report['import_relations'] = changes.get('suggested_edges', [])
        report['directories'] = _extract_dirs(changes.get('new_files', []))
    if level is None or level == "L4":
        struct_files = [f for f in changes.get('new_files', []) if f.get('members')]
        if struct_files:
            report['struct_data'] = [{'file': f['path'], 'structs': f['members']} for f in struct_files]
    if level is None or level == "L1":
        report['l1_externals'] = changes.get('l1_externals', [])

    if level is None:
        report['orphaned_nodes'] = changes.get('orphaned_nodes', [])
        report['deleted_files'] = changes.get('deleted_files', [])
        report['modified_files'] = changes.get('modified_files', [])

    return report


def _format_file_list(files: List[Dict]) -> List[Dict]:
    """Format new_file entries for AI report."""
    return [{'path': f['path'], 'type': f.get('type', 'service'), 'lines': f.get('lines', 0),
             'has_struct': bool(f.get('members'))} for f in files]


def _extract_dirs(files: List[Dict]) -> Dict[str, List[str]]:
    """Extract directory structure from file list."""
    dirs: Dict[str, List[str]] = {}
    for f in files:
        parts = f['path'].split('/')
        d = '/'.join(parts[:-1]) if len(parts) > 1 else '.'
        dirs.setdefault(d, []).append(parts[-1])
    return dict(sorted(dirs.items()))


def _invoke_generator(yaml_content: str, output_path: str):
    """Invoke layout_generator to produce .drawio from YAML."""
    import subprocess, tempfile
    generator = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'layout_generator.py')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        tmp = f.name
    try:
        result = subprocess.run(
            [sys.executable, generator, '--input', tmp, '--output', output_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            print(result.stdout.strip())
        else:
            print(f"Error: {result.stderr.strip()}", file=sys.stderr)
            sys.exit(1)
    finally:
        os.unlink(tmp)


if __name__ == '__main__':
    main()
