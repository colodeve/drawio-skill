"""
Import Graph — Build import dependency graph from source files and suggest edges.

Usage:
    from scripts.import_graph import build_import_graph, suggest_edges
    graph = build_import_graph(project_root, file_paths)
    edges = suggest_edges(graph, existing_nodes)
"""

import os
import re
from collections import defaultdict
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass, field

from scripts.analyzer import extract_imports, structure_hash, content_hash, classify_change


@dataclass
class ImportGraphNode:
    """A single file in the import graph."""
    path: str                    # relative path from project root
    abs_path: str
    imports: List[str] = field(default_factory=list)   # paths this file imports
    imported_by: List[str] = field(default_factory=list)  # paths that import this
    content_fingerprint: str = ""
    structure_fingerprint: str = ""


class ImportGraph:
    """Directed import dependency graph."""

    def __init__(self):
        self.nodes: Dict[str, ImportGraphNode] = {}

    def add_file(self, rel_path: str, abs_path: str):
        if rel_path in self.nodes:
            return
        node = ImportGraphNode(
            path=rel_path,
            abs_path=abs_path,
            content_fingerprint=content_hash(abs_path),
            structure_fingerprint=structure_hash(abs_path),
        )
        self.nodes[rel_path] = node

    def add_import(self, from_path: str, to_path: str):
        if from_path in self.nodes and to_path not in self.nodes[from_path].imports:
            self.nodes[from_path].imports.append(to_path)
        if to_path in self.nodes and from_path not in self.nodes[to_path].imported_by:
            self.nodes[to_path].imported_by.append(from_path)

    def get_node(self, path: str) -> Optional[ImportGraphNode]:
        return self.nodes.get(path)


_EXT_PRIORITY = {
    ".ts": 0, ".tsx": 0, ".js": 0, ".jsx": 0,
    ".py": 1, ".go": 2, ".rs": 3, ".java": 4,
    ".rb": 5, ".php": 6, ".c": 7, ".cpp": 7,
    ".cs": 8, ".kt": 9, ".swift": 10,
}


def _resolve_import_source(imp: str, file_dir: str, all_files: Dict[str, str]) -> Optional[str]:
    """Resolve an import string to a file path in the project.

    Supports:
    - Relative imports: ./foo, ../bar/baz
    - Python dot notation: src.utils → src/utils.py
    - Directory imports: src/ → src/__init__.py or src/index.ts
    - C/C++ includes: "kernel/param.h" → kernel/param.h
    """
    path_candidate = imp.replace(".", "/")
    candidates_to_try = [path_candidate]

    if imp.startswith(("./", "../")):
        joined = os.path.normpath(os.path.join(file_dir, imp))
        candidates_to_try = [joined]
    elif path_candidate != imp:
        candidates_to_try.append(imp)

    extensions = [".ts", ".tsx", ".js", ".jsx", ".py", ".go", ".rs",
                  ".java", ".rb", ".php", ".dart", ".kt", ".swift", ".scala",
                  ".c", ".cpp", ".h", ".hpp", ".cs"]

    for base in candidates_to_try:
        for ext in extensions:
            candidate = base + ext
            if candidate in all_files:
                return candidate
            # Directory import: src → src/__init__.py or src/index.ts
            idx_py = os.path.join(base, "__init__" + ext)
            if ext == ".py" and idx_py in all_files:
                return idx_py
            idx = os.path.join(base, f"index{ext}")
            if idx in all_files:
                return idx
            idx2 = os.path.join(base, f"mod{ext}")
            if ext == ".rs" and idx2 in all_files:
                return idx2

    # C/C++ include resolution: try adding relative prefixes
    if not imp.startswith(("./", "../", "/")):
        for prefix in ["", "kernel/", "src/", "include/", "lib/"]:
            for ext in [".h", ".hpp", ".c", ".cpp"]:
                candidate = prefix + imp
                if not candidate.endswith(ext):
                    candidate_candidate = candidate + ext
                    if candidate_candidate in all_files:
                        return candidate_candidate
                if candidate in all_files:
                    return candidate

    # Fallback: match by last component name
    last_part = imp.rstrip(".").rpartition(".")[2] or imp.rpartition("/")[2] or imp
    if not last_part:
        return None
    matches = []
    for fpath in all_files:
        base = os.path.splitext(os.path.basename(fpath))[0]
        if base == last_part:
            matches.append((fpath, _EXT_PRIORITY.get(os.path.splitext(fpath)[1].lower(), 99)))
    if matches:
        matches.sort(key=lambda x: x[1])
        return matches[0][0]

    return None


def build_import_graph(project_root: str, file_paths: List[str]) -> ImportGraph:
    """
    Build a complete import dependency graph.

    Args:
        project_root: Absolute path to project root
        file_paths: List of absolute file paths to analyze

    Returns:
        ImportGraph with resolved dependencies
    """
    graph = ImportGraph()

    # Map all file paths for resolution
    abs_to_rel: Dict[str, str] = {}
    rel_to_ext: Dict[str, str] = {}
    for fp in file_paths:
        rel = os.path.relpath(fp, project_root).replace(os.sep, "/")
        abs_to_rel[fp] = rel
        ext = os.path.splitext(fp)[1].lower()
        rel_to_ext[rel] = ext
        graph.add_file(rel, fp)

    # Resolve imports for each file
    for abs_path, rel_path in abs_to_rel.items():
        imports = extract_imports(abs_path)
        for imp in imports:
            file_dir = os.path.dirname(rel_path)
            resolved = _resolve_import_source(imp.source_module, file_dir, rel_to_ext)
            if resolved:
                graph.add_import(rel_path, resolved)

    return graph


def suggest_edges(
    import_graph: ImportGraph,
    existing_nodes: List[Tuple[str, str]],    # [(node_id, file_path)]
) -> List[Dict]:
    """
    Suggest edges between diagram nodes based on import relationships.

    Args:
        import_graph: Built ImportGraph
        existing_nodes: List of (node_id, relative_file_path) from the diagram

    Returns:
        List of edge dicts: {from, to, label, style}
    """
    # Build file → list of node_ids (one file can have multiple diagram nodes)
    file_to_nodes: Dict[str, List[str]] = {}
    for nid, fpath in existing_nodes:
        file_to_nodes.setdefault(fpath, []).append(nid)

    edges: List[Dict] = []
    seen_pairs: Set[Tuple[str, str]] = set()

    for rel_path, node in import_graph.nodes.items():
        src_ids = file_to_nodes.get(rel_path, [])
        if not src_ids:
            continue

        for imported_path in node.imports:
            tgt_ids = file_to_nodes.get(imported_path, [])
            if not tgt_ids:
                continue

            for src_id in src_ids:
                for tgt_id in tgt_ids:
                    if src_id == tgt_id:
                        continue
                    pair = (src_id, tgt_id) if src_id < tgt_id else (tgt_id, src_id)
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)

                    same_dir = os.path.dirname(rel_path) == os.path.dirname(imported_path)
                    edges.append({
                        "from": src_id,
                        "to": tgt_id,
                        "label": "imports" if same_dir else "depends on",
                        "style": "solid" if same_dir else "dashed",
                    })

    return edges


def compute_project_fingerprints(project_root: str, file_paths: List[str]) -> Dict[str, Dict]:
    """
    Compute content and structure fingerprints for all project files.
    Returns dict mapping relative path → {content_hash, structure_hash, lines}.
    """
    result = {}
    for fp in file_paths:
        rel = os.path.relpath(fp, project_root).replace(os.sep, "/")
        result[rel] = {
            "content_hash": content_hash(fp),
            "structure_hash": structure_hash(fp),
            "lines": _count_lines(fp),
        }
    return result


def _count_lines(file_path: str) -> int:
    try:
        with open(file_path, "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


def detect_changed_files(
    old_fingerprints: Dict[str, Dict],
    new_fingerprints: Dict[str, Dict],
) -> Dict[str, str]:
    """
    Compare old and new fingerprints to classify changes.

    Returns: dict of rel_path → change_type ("new", "deleted", "structural", "cosmetic", "none")
    """
    changes: Dict[str, str] = {}

    old_paths = set(old_fingerprints.keys())
    new_paths = set(new_fingerprints.keys())

    for path in new_paths - old_paths:
        changes[path] = "new"
    for path in old_paths - new_paths:
        changes[path] = "deleted"

    for path in old_paths & new_paths:
        old = old_fingerprints[path]
        new = new_fingerprints[path]
        if old["content_hash"] == new["content_hash"]:
            changes[path] = "none"
        elif old["structure_hash"] == new["structure_hash"]:
            changes[path] = "cosmetic"
        else:
            changes[path] = "structural"

    return changes
