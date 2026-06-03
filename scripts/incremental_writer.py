#!/usr/bin/env python3
"""
Incremental Writer — Incrementally generate/update code from diagram changes.

Usage:
    # Detect diagram-to-code differences
    python incremental_writer.py --drawio diagram.drawio --project-root . --diff

    # Apply scaffold plan
    python incremental_writer.py --plan scaffold.yaml --apply

    # Full pipeline
    python incremental_writer.py --drawio diagram.drawio --project-root . --auto
"""

import os
import sys
import argparse
import yaml
import shutil
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.xml_parser import XmlParser, NodeInfo


class CodeScaffolder:
    """Generates minimal code stubs from diagram scaffold YAML.

    This class only creates empty placeholder files and does basic text injection.
    The actual code generation is done by AI based on the structured YAML plan.
    """

    def __init__(self, project_root: str):
        self.project_root = os.path.abspath(project_root)

    COMMENT_SYNTAX = {
        'python': '#',
        'typescript': '//',
        'javascript': '//',
        'java': '//',
        'go': '//',
        'rust': '//',
        'ruby': '#',
        'php': '//',
        'swift': '//',
        'kotlin': '//',
        'c': '//',
        'cpp': '//',
        'csharp': '//',
    }

    @staticmethod
    def _comment_char(language: str) -> str:
        return CodeScaffolder.COMMENT_SYNTAX.get(language, '#')

    def create_file(self, spec: Dict[str, Any]) -> str:
        """Create or merge a code file from diagram scaffold YAML.

        If the file already exists, merges new imports and methods in-place
        instead of overwriting. If it doesn't exist, creates a placeholder
        for AI to fill.
        """
        path = spec['path']
        full_path = os.path.join(self.project_root, path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

        language = spec.get('language', 'python')
        c = self._comment_char(language)

        # ── If file exists: merge imports + append method stubs ──
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()
            original = content
            lines = content.split("\n")

            # Merge new imports (skip duplicates)
            imports_to_add = spec.get("imports", [])
            for imp in imports_to_add:
                if "default" in imp:
                    line = f"from {imp['from']} import {imp['default']}"
                else:
                    line = f"from {imp['from']} import {', '.join(imp['names'])}"
                if line not in content:
                    last_import = -1
                    for i, l in enumerate(lines):
                        if l.strip().startswith(("import ", "from ", "# import", "// import")):
                            last_import = i
                    lines.insert(last_import + 1 if last_import >= 0 else 0, line)

            # Append new method stubs inside the class body
            class_name = spec.get("class_name", "")
            if class_name:
                from scripts.analyzer import find_block
                block_start, block_end = find_block(full_path, class_name)
                if block_start is not None and block_end is not None:
                    existing = "\n".join(lines)
                    for m in spec.get("methods", []):
                        sig = m.get("name", "unnamed")
                        if sig not in existing:
                            params = ", ".join(p["name"] for p in m.get("params", []))
                            indent = "    "
                            stub = f"\n{indent}def {sig}({params}):\n{indent}    raise NotImplementedError  # TODO: implement from diagram\n"
                            lines.insert(block_end, stub)

            content = "\n".join(lines)
            if content != original:
                backup = f"{full_path}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                shutil.copy2(full_path, backup)
                with open(full_path, "w", encoding="utf-8") as f:
                    f.write(content)
                print(f"Merged changes into: {path}")
            else:
                print(f"No changes needed: {path}")
            return full_path

        # ── New file: create placeholder ──
        placeholder = [f"{c} {spec.get('class_name', 'Generated')} — generated from drawio diagram"]
        placeholder.append(f"{c} AI will implement based on: {spec.get('template', 'class')}")
        placeholder.append("")

        imports = spec.get("imports", [])
        for imp in imports:
            if "default" in imp:
                placeholder.append(f"from {imp['from']} import {imp['default']}")
            else:
                placeholder.append(f"from {imp['from']} import {', '.join(imp['names'])}")
        if imports:
            placeholder.append("")

        class_name = spec.get("class_name", "Unnamed")
        placeholder.append(f"class {class_name}:")
        for m in spec.get("methods", []):
            params = ", ".join(p["name"] for p in m.get("params", []))
            placeholder.append(f"    def {m['name']}({params}):")
            placeholder.append(f"        raise NotImplementedError  # TODO: implement")
        placeholder.append("")

        content = "\n".join(placeholder) + "\n"
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Created placeholder: {path}")
        return full_path

    def modify_file(self, path: str, operations: List[Dict[str, Any]]) -> bool:
        """Apply modifications using analyzer for positioning."""
        from scripts.analyzer import find_block

        full_path = os.path.join(self.project_root, path)
        if not os.path.exists(full_path):
            print(f"Warning: File not found: {full_path}")
            return False

        with open(full_path, "r", encoding="utf-8") as f:
            content = f.read()
        original = content

        for op in operations:
            op_type = op["type"]

            if op_type == "import":
                line = op.get("content", "")
                if line and line not in content:
                    lines = content.split("\n")
                    last_import = -1
                    for i, l in enumerate(lines):
                        if l.strip().startswith(("import ", "from ", "# import")):
                            last_import = i
                    lines.insert(last_import + 1 if last_import >= 0 else 0, line)
                    content = "\n".join(lines)

            elif op_type in ("inject_method", "inject_property"):
                target_class = op.get("target_class", "")
                block_start, block_end = find_block(full_path, target_class)
                if block_start is not None and block_end is not None:
                    source_lines = content.split("\n")
                    # Insert before the closing brace of the class
                    insert_line = block_end
                    while insert_line > block_start and source_lines[insert_line].strip() == "":
                        insert_line -= 1
                    source_lines.insert(insert_line, f"    # TODO: {op.get('method', op.get('property', ''))}")
                    content = "\n".join(source_lines)

        if content != original:
            backup = f"{full_path}.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(full_path, backup)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"Modified: {path}")
            return True

        return False


class IncrementalWriter:
    """Handles incremental code generation from diagram changes."""

    def __init__(self, drawio_path: str, project_root: str):
        self.drawio_path = os.path.abspath(drawio_path)
        self.project_root = os.path.abspath(project_root)
        self.scaffolder = CodeScaffolder(project_root)
        self.parser = XmlParser(drawio_path)
        self.diagram_data = self.parser.parse()

    EXCLUDE_DIRS = {"node_modules", ".git", ".svn", "__pycache__", ".venv", "venv", "dist", "build", ".next", ".turbo", "target", "bin", "obj", "vendor", ".drawio-backups"}

    def detect_changes(self, exclude_dirs: Optional[set] = None) -> Dict[str, Any]:
        """Detect differences between diagram and code."""
        changes = {
            'new_nodes': [],
            'deleted_nodes': [],
            'modified_labels': [],
            'orphaned_files': [],
        }

        skip = exclude_dirs or self.EXCLUDE_DIRS
        file_to_nodes: Dict[str, List[NodeInfo]] = {}
        for node in self.diagram_data.nodes:
            if node.path:
                file_to_nodes.setdefault(node.path, []).append(node)

        for node in self.diagram_data.nodes:
            if not node.path:
                continue
            full_path = os.path.join(os.path.dirname(self.drawio_path), node.path)
            if not os.path.exists(full_path):
                changes['new_nodes'].append({
                    'id': node.id,
                    'label': node.label,
                    'path': node.path,
                    'type': self._infer_type_from_label(node.label)
                })

        for root, dirs, files in os.walk(self.project_root):
            dirs[:] = [d for d in dirs if d not in skip]
            for filename in files:
                if filename.endswith(('.ts', '.js', '.py', '.java', '.go', '.rs', '.rb', '.php')):
                    full_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(full_path, os.path.dirname(self.drawio_path))
                    rel_path = rel_path.replace(os.sep, '/')
                    if rel_path not in file_to_nodes:
                        changes['orphaned_files'].append(rel_path)

        return changes

    def _infer_type_from_label(self, label: str) -> str:
        """Infer code template type from node label."""
        label_lower = label.lower()
        if 'service' in label_lower:
            return 'class'
        elif 'controller' in label_lower or 'handler' in label_lower:
            return 'class'
        elif 'interface' in label_lower or 'dto' in label_lower:
            return 'interface'
        elif 'enum' in label_lower:
            return 'enum'
        elif 'util' in label_lower or 'helper' in label_lower:
            return 'function'
        return 'class'

    def generate_scaffold_yaml(self, changes: Dict[str, Any]) -> str:
        """Generate scaffold YAML — AI uses this to create actual code."""
        scaffold = {
            'action': 'scaffold',
            'existing_code': self.project_root,
        }

        if changes['new_nodes']:
            scaffold['create_files'] = []
            for node in changes['new_nodes']:
                lang = self._infer_language(node['path'])
                scaffold['create_files'].append({
                    'path': node['path'],
                    'language': lang,
                    'template': self._infer_type_from_label(node['label']),
                    'class_name': self._to_class_name(node['label']),
                    'description': node['label'],
                    'imports': [],
                    'methods': [{'name': 'execute', 'return_type': 'any'}],
                })

        return yaml.dump(scaffold, allow_unicode=True, sort_keys=False)

    def _infer_language(self, path: str) -> str:
        ext = os.path.splitext(path)[1].lower()
        return {
            ".py": "python", ".ts": "typescript", ".js": "javascript",
            ".tsx": "typescript", ".jsx": "javascript",
            ".java": "java", ".go": "go", ".rs": "rust",
            ".rb": "ruby", ".php": "php",
        }.get(ext, "unknown")

    def _to_class_name(self, label: str) -> str:
        """Convert label to class name."""
        # Remove type suffixes like (Service)
        label = re.sub(r'\s*\([^)]*\)\s*', '', label)
        # Remove () from function names
        label = label.replace('()', '')
        # PascalCase
        return ''.join(word.capitalize() for word in re.split(r'[_\s]+', label) if word)

    def apply_scaffold(self, scaffold_yaml_path: str) -> bool:
        """Apply scaffold YAML to generate code."""
        with open(scaffold_yaml_path, 'r', encoding='utf-8') as f:
            plan = yaml.safe_load(f)

        created = []
        modified = []

        # Create files
        for spec in plan.get('create_files', []):
            path = self.scaffolder.create_file(spec)
            created.append(path)

        # Modify files
        for mod in plan.get('modify_files', []):
            if self.scaffolder.modify_file(mod['path'], mod['operations']):
                modified.append(mod['path'])

        # Delete files (move to backup with unique name)
        for del_path in plan.get('delete_files', []):
            full_path = os.path.join(self.project_root, del_path)
            if os.path.exists(full_path):
                backup_dir = os.path.join(self.project_root, '.drawio-backups')
                os.makedirs(backup_dir, exist_ok=True)
                base_name = os.path.basename(del_path)
                backup_path = os.path.join(backup_dir, base_name)
                # Avoid overwriting existing backups
                counter = 1
                while os.path.exists(backup_path):
                    name, ext = os.path.splitext(base_name)
                    backup_path = os.path.join(backup_dir, f"{name}_{counter}{ext}")
                    counter += 1
                shutil.move(full_path, backup_path)
                print(f"Moved to backup: {del_path} -> {os.path.relpath(backup_path, self.project_root)}")

        print(f"\nScaffold applied:")
        print(f"  Created: {len(created)} files")
        print(f"  Modified: {len(modified)} files")

        return True


def main():
    parser = argparse.ArgumentParser(description='Incremental diagram writer')
    parser.add_argument('--drawio', '-d', help='Source .drawio file')
    parser.add_argument('--project-root', '-p', default='.', help='Project root')
    parser.add_argument('--diff', action='store_true', help='Detect changes')
    parser.add_argument('--plan', help='Scaffold YAML file')
    parser.add_argument('--apply', action='store_true', help='Apply scaffold')
    parser.add_argument('--auto', action='store_true', help='Auto mode')
    parser.add_argument('--output', '-o', help='Output scaffold YAML')
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--exclude", nargs="+",
        default=[],
        help="Additional directories to exclude from scanning"
    )
    args = parser.parse_args()

    if args.diff or args.auto:
        if not args.drawio:
            print("Error: --drawio required", file=sys.stderr)
            sys.exit(1)
        writer = IncrementalWriter(args.drawio, args.project_root)
        extra_exclude = set(args.exclude) if args.exclude else set()
        changes = writer.detect_changes(exclude_dirs=writer.EXCLUDE_DIRS | extra_exclude)
        if args.verbose:
            print(f"[verbose] Scanning {args.project_root}")
            print(f"[verbose] New nodes: {len(changes['new_nodes'])}")
            print(f"[verbose] Orphaned files: {len(changes['orphaned_files'])}")

        if args.diff:
            print("# Diagram-to-Code Changes")
            print(yaml.dump(changes, allow_unicode=True, sort_keys=False))
            print("\n# Suggested Scaffold")
            print(writer.generate_scaffold_yaml(changes))

        if args.auto:
            scaffold_yaml = writer.generate_scaffold_yaml(changes)
            temp_plan = '/tmp/drawio_auto_scaffold.yaml'
            with open(temp_plan, 'w') as f:
                f.write(scaffold_yaml)
            writer.apply_scaffold(temp_plan)

    elif args.plan:
        writer = IncrementalWriter(args.drawio or '', args.project_root)
        # When --drawio is not given, skip diagram parsing
        if not args.drawio or not os.path.exists(args.drawio):
            writer.diagram_data = None
        writer.apply_scaffold(args.plan)

    else:
        print("Use --diff to detect changes, --plan --apply to scaffold, or --auto for full pipeline")


if __name__ == '__main__':
    main()
