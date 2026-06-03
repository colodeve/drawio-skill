"""Path resolution and validation utilities."""

import os
import re
from pathlib import Path, PureWindowsPath
from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass, field


@dataclass
class PathResolutionResult:
    """Result of a path resolution operation."""
    original_path: str
    resolved_path: Optional[str] = None
    is_valid: bool = False
    absolute_path: Optional[str] = None
    error: Optional[str] = None
    suggestion: Optional[str] = None


@dataclass
class PathFix:
    """Represents a path fix operation."""
    node_id: str
    node_label: str
    original_path: str
    fixed_path: str
    is_fixed: bool = False


class PathResolver:
    """Resolves and validates hedietLinkedDataV1 paths in drawio files."""

    def __init__(self, drawio_file: str, project_root: Optional[str] = None):
        self.drawio_file = os.path.abspath(drawio_file)
        self.drawio_dir = os.path.dirname(self.drawio_file)
        self.project_root = project_root or self._find_project_root()

    def _find_project_root(self) -> str:
        """Find project root by looking for common markers."""
        current = self.drawio_dir
        markers = ["package.json", "tsconfig.json", ".git", "src", "pyproject.toml"]

        while current:
            for marker in markers:
                if os.path.exists(os.path.join(current, marker)):
                    return current
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

        return self.drawio_dir

    def resolve_path(self, relative_path: str) -> PathResolutionResult:
        """Resolve a relative path from the drawio file location."""
        result = PathResolutionResult(original_path=relative_path)

        full_path = os.path.join(self.drawio_dir, relative_path)
        abs_path = os.path.abspath(full_path)

        result.absolute_path = abs_path

        if os.path.exists(abs_path):
            result.is_valid = True
            result.resolved_path = abs_path
            return result

        if self.project_root and self.project_root != self.drawio_dir:
            alt_path = os.path.join(self.project_root, relative_path.lstrip("./"))
            if os.path.exists(alt_path):
                correct_rel = os.path.relpath(alt_path, self.drawio_dir).replace(os.sep, '/')
                result.suggestion = correct_rel
                result.error = f"Path resolves from project root but relative path is wrong"
                return result

        result.is_valid = False
        result.error = "File not found"
        return result

    def calculate_correct_path(self, target_file: str, drawio_auto_add_parent: bool = True) -> str:
        """Calculate the correct relative path from drawio to target file.
        
        Args:
            target_file: The absolute path to the target file
            drawio_auto_add_parent: If True, add an extra parent directory traversal
                                   because draw.io internally adds one level of ..
        """
        target_abs = os.path.abspath(target_file)
        rel_path = os.path.relpath(target_abs, self.drawio_dir)
        rel_path = rel_path.replace(os.sep, '/')
        
        # 如果draw.io内部会自动加上一层 ..，我们需要在这里多加一层
        if drawio_auto_add_parent and not rel_path.startswith('/'):
            # 如果已经是绝对路径或已经有足够的..，不需要再加
            if not rel_path.startswith('..'):
                rel_path = '../' + rel_path
            elif rel_path.startswith('../'):
                # 如果已经有..，再加一层
                rel_path = '../' + rel_path
        
        return rel_path

    def validate_all_paths(self, nodes: List[Any]) -> Dict[str, PathResolutionResult]:
        """Validate paths for multiple nodes."""
        results = {}
        for node in nodes:
            if hasattr(node, 'path') and node.path:
                results[node.id] = self.resolve_path(node.path)
        return results

    def fix_path(self, original_path: str, target_file: str) -> str:
        """Calculate the correct relative path for a target file."""
        return self.calculate_correct_path(target_file)


def calculate_relative_path(drawio_file: str, target_file: str) -> str:
    """Calculate relative path from drawio file to target file."""
    drawio_dir = os.path.dirname(os.path.abspath(drawio_file))
    target_abs = os.path.abspath(target_file)
    rel = os.path.relpath(target_abs, drawio_dir)
    return rel.replace(os.sep, '/')


def validate_path(drawio_file: str, relative_path: str) -> Tuple[bool, Optional[str]]:
    """Validate a relative path from a drawio file.

    Returns:
        Tuple of (is_valid, error_message)
    """
    drawio_dir = os.path.dirname(os.path.abspath(drawio_file))
    full_path = os.path.join(drawio_dir, relative_path)

    if not os.path.exists(full_path):
        return False, f"File not found: {full_path}"

    if not os.path.isfile(full_path):
        return False, f"Path is not a file: {full_path}"

    return True, None


def normalize_path(path: str) -> str:
    """Normalize a path to use forward slashes."""
    return path.replace(os.sep, '/')


def get_file_info(file_path: str) -> Dict[str, Any]:
    """Get information about a file."""
    import stat

    if not os.path.exists(file_path):
        return {"exists": False}

    st = os.stat(file_path)
    return {
        "exists": True,
        "size": st.st_size,
        "lines": get_line_count(file_path),
        "modified": st.st_mtime,
        "is_file": os.path.isfile(file_path),
        "is_dir": os.path.isdir(file_path)
    }


def get_line_count(file_path: str) -> int:
    """Get the number of lines in a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except (OSError, IOError):
        return 0


def standardize_path_format(path: str) -> str:
    """Standardize path format for cross-platform compatibility."""
    path = path.strip()

    path = path.replace("\\", "/")

    if not path.startswith(("./", "../", "/")):
        path = "./" + path

    path = re.sub(r"/+", "/", path)

    return path
