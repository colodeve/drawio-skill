"""
Git Diff Reader — Bridge between git diff and drawio-skill toolchain.

Provides:
  - git diff parsing for code and drawio files
  - Drawio XML diff detection (nodes/edges added/removed/modified)
  - Safe branch creation for all write operations
"""

import os
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class DrawioDiff:
    """Parsed diff between two versions of a .drawio file."""
    added_nodes: List[Dict] = field(default_factory=list)
    removed_nodes: List[Dict] = field(default_factory=list)
    modified_nodes: List[Dict] = field(default_factory=list)
    added_edges: List[Dict] = field(default_factory=list)
    removed_edges: List[Dict] = field(default_factory=list)
    modified_edges: List[Dict] = field(default_factory=list)


def _run_git(args: List[str], cwd: str) -> Tuple[bool, str]:
    """Run a git command safely. Returns (success, stdout_or_error)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True, text=True, timeout=60,
            cwd=cwd
        )
        if result.returncode == 0:
            return True, result.stdout
        return False, result.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)


def is_git_repo(project_root: str) -> bool:
    """Check if project_root is inside a git repository."""
    ok, _ = _run_git(["rev-parse", "--git-dir"], project_root)
    return ok


def check_dirty(project_root: str) -> bool:
    """Return True if there are uncommitted changes."""
    ok, out = _run_git(["status", "--porcelain"], project_root)
    return ok and bool(out.strip())


def safe_branch(project_root: str, prefix: str = "drawio-skill") -> Optional[str]:
    """Create a safe branch for write operations.
    
    Returns the branch name, or None if git is unavailable.
    Does NOT switch to the branch — caller must checkout.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    branch = f"{prefix}/{timestamp}"

    # Stash dirty changes first
    dirty = check_dirty(project_root)
    if dirty:
        ok, _ = _run_git(["stash", "push", "-m", f"auto-stash-{timestamp}"], project_root)
        if not ok:
            return None

    ok, _ = _run_git(["checkout", "-b", branch], project_root)
    if not ok:
        return None
    return branch


def commit_and_return(project_root: str, message: str, branch: Optional[str] = None):
    """Commit all changes and optionally switch back to previous branch."""
    _run_git(["add", "-A"], project_root)
    ok, _ = _run_git(["commit", "-m", f"drawio-skill: {message}"], project_root)
    if ok:
        print(f"Committed: {message}")
    if branch:
        # Switch back to original branch
        _run_git(["checkout", "-"], project_root)


def changed_files(ref: str = "HEAD", project_root: str = ".") -> List[str]:
    """Get list of files changed since ref using git diff.
    
    Returns file paths relative to project_root (tracked changes only).
    Use untracked_files() for new untracked files.
    """
    ok, out = _run_git(["diff", "--name-only", ref], project_root)
    if not ok:
        return []
    return [f.strip() for f in out.split("\n") if f.strip()]


def untracked_files(project_root: str = ".") -> List[str]:
    """Get list of untracked files (not yet staged/committed).
    
    Returns file paths relative to project_root.
    """
    ok, out = _run_git(["ls-files", "--others", "--exclude-standard"], project_root)
    if not ok:
        return []
    return [f.strip() for f in out.split("\n") if f.strip()]


def file_diff(file_path: str, ref: str = "HEAD", project_root: str = ".") -> Optional[str]:
    """Get unified diff for a specific file since ref. Returns None on failure."""
    ok, out = _run_git(["diff", ref, "--", file_path], project_root)
    if not ok:
        return None
    return out


def file_content_at_ref(file_path: str, ref: str = "HEAD", project_root: str = ".") -> Optional[str]:
    """Get the content of a file at a specific git ref. Returns None on failure."""
    ok, out = _run_git(["show", f"{ref}:{file_path}"], project_root)
    if not ok:
        return None
    return out


def drawio_diff(drawio_path: str, ref: str = "HEAD", project_root: str = ".") -> DrawioDiff:
    """Compare current drawio file with its version at ref.

    Parses both XML files and compares nodes/edges by their id attribute.
    Returns a DrawioDiff with added/removed/modified elements.
    """
    result = DrawioDiff()

    rel_path = os.path.relpath(drawio_path, project_root).replace(os.sep, "/")
    old_xml_str = file_content_at_ref(rel_path, ref, project_root)
    if old_xml_str is None:
        return result  # New file: all nodes are "added" — skip, handled by --diff

    old_nodes, old_edges = _parse_drawio_elements(old_xml_str)
    new_nodes, new_edges = _parse_drawio_elements_file(drawio_path)

    old_node_map = {n["id"]: n for n in old_nodes}
    new_node_map = {n["id"]: n for n in new_nodes}

    all_node_ids = set(old_node_map.keys()) | set(new_node_map.keys())
    for nid in all_node_ids:
        old = old_node_map.get(nid)
        new = new_node_map.get(nid)
        if old and new:
            if old["label"] != new["label"] or old.get("path") != new.get("path"):
                result.modified_nodes.append(new)
        elif new:
            result.added_nodes.append(new)
        elif old:
            result.removed_nodes.append(old)

    old_edge_set = {(e["source"], e["target"]) for e in old_edges}
    new_edge_set = {(e["source"], e["target"]) for e in new_edges}

    for e in new_edges:
        if (e["source"], e["target"]) not in old_edge_set:
            result.added_edges.append(e)
    for e in old_edges:
        if (e["source"], e["target"]) not in new_edge_set:
            result.removed_edges.append(e)

    return result


def _parse_drawio_elements(xml_str: str) -> Tuple[List[Dict], List[Dict]]:
    """Parse drawio XML string and return (nodes, edges) lists."""
    nodes, edges = [], []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return nodes, edges

    for elem in root.iter():
        tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
        if tag not in ("object", "mxCell"):
            continue

        # Check if edge
        style = elem.get("style", "")
        if 'edge="1"' in str(ET.tostring(elem, encoding="unicode")) or \
           elem.get("edge") == "1" or "edgeStyle=" in style:
            edges.append({
                "id": elem.get("id", ""),
                "source": elem.get("source", ""),
                "target": elem.get("target", ""),
                "label": elem.get("label", elem.get("value", "")),
            })
        else:
            nodes.append({
                "id": elem.get("id", ""),
                "label": elem.get("label", elem.get("value", "")),
                "path": elem.get("hedietLinkedDataV1_path", ""),
            })

    return nodes, edges


def _parse_drawio_elements_file(file_path: str) -> Tuple[List[Dict], List[Dict]]:
    """Parse drawio file and return (nodes, edges) lists."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return _parse_drawio_elements(f.read())
    except Exception:
        return [], []


def parse_git_diff(diff_str: str) -> List[Dict[str, Any]]:
    """Parse a unified git diff into structured change entries.
    
    Each entry: {type: "add"|"del", line: int, content: str}
    Useful for AI to understand the semantic meaning of a code change.
    """
    changes = []
    if not diff_str:
        return changes

    for line in diff_str.split("\n"):
        if line.startswith("+"):
            changes.append({"type": "add", "content": line[1:]})
        elif line.startswith("-"):
            changes.append({"type": "del", "content": line[1:]})

    return changes


def code_diff_summary(file_path: str, ref: str = "HEAD", project_root: str = ".") -> Optional[str]:
    """Get a structured summary of code changes for AI consumption.
    
    Returns markdown-formatted diff or None if no changes.
    """
    diff = file_diff(file_path, ref, project_root)
    if not diff:
        return None

    lines = diff.split("\n")
    # Strip header lines (diff --git, index, ---, +++, @@)
    body = [l for l in lines if l.startswith(("+", "-")) and not l.startswith(("---", "+++"))]

    summary = f"## Changes in {file_path}\n\n"
    adds = [l[1:] for l in body if l.startswith("+")]
    dels = [l[1:] for l in body if l.startswith("-")]

    if adds:
        summary += "### Added\n```\n" + "\n".join(adds[:20]) + "\n```\n"
        if len(adds) > 20:
            summary += f"... and {len(adds) - 20} more added lines\n"
    if dels:
        summary += "### Removed\n```\n" + "\n".join(dels[:20]) + "\n```\n"
        if len(dels) > 20:
            summary += f"... and {len(dels) - 20} more removed lines\n"

    return summary


def classify_change_from_diff(diff_str: str) -> str:
    """Classify a code change as cosmetic or structural based on diff content."""
    if not diff_str:
        return "none"

    changes = parse_git_diff(diff_str)
    structural_keywords = [
        "def ", "class ", "return ", "import ", "from ", "async ",
        "function ", "interface ", "type ", "enum ", "struct ",
        "impl ", "fn ", "pub ", "const ", "let ", "var ",
        "if ", "for ", "while ", "match ", "switch ", "case ",
        "=>", "=", "(", "{", "<",
        "#include", "#define", "typedef",
    ]

    for c in changes:
        content = c["content"].strip()
        if content and not content.startswith(("#", "//", "--", "/*", "*", "//")):
            if any(kw in content for kw in structural_keywords):
                return "structural"

    return "cosmetic" if changes else "none"
