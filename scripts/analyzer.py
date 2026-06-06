"""
Code Analyzer — Language-aware code block finder and import/extract analyzer.

Uses Python ast for .py; improved regex with string/comment-aware brace matching for
JS/TS/Java/Go/Rust/C/C++/C#/Kotlin/Swift/ PHP/Dart; keyword matching for Ruby/Python/Shell/Lua.

Features:
  - find_block(file, name) -> (start_line, end_line) 0-indexed
  - extract_imports(file_path) -> [ImportInfo]        dependency list
  - structure_hash(file_path) -> str                  structural fingerprint
"""

import ast
import hashlib
import os
import re
from typing import Optional, Tuple, List, Dict, Set
from dataclasses import dataclass


# ── language table ──────────────────────────────────────────────────────────

EXT_LANG: Dict[str, str] = {
    ".py": "python", ".pyw": "python",
    ".ts": "typescript", ".tsx": "tsx", ".js": "javascript", ".jsx": "jsx",
    ".mjs": "javascript", ".cjs": "javascript", ".mts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "hpp",
    ".cs": "csharp",
    ".kt": "kotlin", ".kts": "kotlin",
    ".swift": "swift",
    ".dart": "dart",
    ".scala": "scala",
    ".lua": "lua",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".pl": "perl",
    ".pm": "perl",
}

# Languages that use curly-brace blocks
BRACE_LANGS = {"typescript", "tsx", "javascript", "jsx", "java", "go", "rust",
               "c", "cpp", "hpp", "csharp", "kotlin", "swift", "dart", "scala",
               "php"}
# Languages that use "end" keyword blocks
END_LANGS = {"ruby", "lua"}
# Languages where indentation determines blocks (Python handled by ast)
INDENT_LANGS = {"python", "shell"}


# ── public types ────────────────────────────────────────────────────────────

@dataclass
class ImportInfo:
    source_module: str
    imported_names: List[str]  # empty if whole-module import
    is_relative: bool = False


@dataclass
class ExportInfo:
    name: str
    kind: str           # "class" | "function" | "variable" | "interface"
    start_line: int
    end_line: int


# ── find_block ──────────────────────────────────────────────────────────────

def find_block(file_path: str, search_name: str) -> Tuple[Optional[int], Optional[int]]:
    ext = os.path.splitext(file_path)[1].lower()
    lang = EXT_LANG.get(ext)
    if lang is None:
        return None, None

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return None, None

    if lang == "python":
        return _find_python_block(file_path, lines, search_name)
    if lang in BRACE_LANGS:
        return _find_brace_block(lines, search_name, lang)
    if lang in END_LANGS:
        return _find_end_block(lines, search_name, lang)
    if lang == "shell":
        return _find_shell_block(lines, search_name)
    return None, None


# ── Python ──────────────────────────────────────────────────────────────────

def _find_python_block(file_path: str, lines: List[str], name: str) -> Tuple[Optional[int], Optional[int]]:
    # Try AST first
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    return node.lineno - 1, node.end_lineno - 1
    except SyntaxError:
        pass

    # Regex fallback — indentation-aware
    pattern = rf"^\s*(?:class|def|async def)\s+{re.escape(name)}\b"
    start = None
    for i, line in enumerate(lines):
        if re.search(pattern, line):
            start = i
            break
    if start is None:
        return None, None

    start_indent = _indent_len(lines[start])
    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _indent_len(lines[i])
        if indent <= start_indent and not stripped.startswith(("@", "def ", "class ", "async def")):
            return start, i - 1
    return start, len(lines) - 1


# ── Curly-brace block (string / comment / regex aware) ──────────────────────

def _find_brace_block(lines: List[str], name: str, lang: str) -> Tuple[Optional[int], Optional[int]]:
    patterns = _brace_patterns(name, lang)
    start = _match_pattern(lines, patterns)
    if start is None:
        return None, None

    brace_depth = 0
    found_open = False
    in_string = None  # None | "'" | '"' | '`'
    in_regex = False
    for i in range(start, len(lines)):
        line = lines[i]
        j = 0
        while j < len(line):
            ch = line[j]
            nc = line[j + 1] if j + 1 < len(line) else ""

            # Toggle string state
            if in_string is None and ch in ("'", '"', '`'):
                # Check if not escaped
                if j == 0 or line[j - 1] != "\\":
                    # Triple-quote check
                    if nc == ch and j + 2 < len(line) and line[j + 2] == ch:
                        in_string = ch * 3
                        j += 3
                        continue
                    in_string = ch
            elif in_string is not None:
                if in_string in ("'", '"', '`') and ch == in_string and (j == 0 or line[j - 1] != "\\"):
                    in_string = None
                elif in_string in ("'''", '"""') and ch == in_string[0] and nc == in_string[0] and j + 2 < len(line) and line[j + 2] == in_string[0]:
                    # Check for triple close
                    k = j + 2
                    if k < len(line) and line[k] == in_string[0]:
                        in_string = None
                        j = k + 1
                        continue

            # Regex literal in JS/TS — /regex/flags after certain tokens
            if in_string is None and lang in ("javascript", "typescript", "tsx", "jsx"):
                if ch == "/" and (j == 0 or line[j - 1] in (" ", "=", "(", "[", "{", "!", "&", "|", ",", ";", ":")):
                    in_regex = not in_regex

            # Count braces (only when not in string/regex)
            if in_string is None and not in_regex:
                if ch == "{":
                    brace_depth += 1
                    found_open = True
                elif ch == "}":
                    brace_depth -= 1

            j += 1

        if in_regex:
            in_regex = False  # reset per line

        if found_open and brace_depth <= 0:
            return start, i

    if not found_open:
        return start, start
    return start, len(lines) - 1


def _brace_patterns(name: str, lang: str) -> List[str]:
    """Language-specific patterns for finding a declaration."""
    kw = re.escape(name)
    pats = []

    # Common patterns
    if lang in ("java", "csharp", "kotlin", "swift", "dart", "scala", "cpp", "c", "hpp"):
        pats.append(rf"^\s*(?:public\s+|private\s+|protected\s+|static\s+|abstract\s+|sealed\s+|override\s+|virtual\s+)*(?:class|interface|struct|enum)\s+{kw}\b")
        func_name = name.split("(")[0].strip()
        pats.append(rf"^\s*(?:public\s+|private\s+|protected\s+|static\s+)*(?:async\s+|unsafe\s+)?(?:void|int|string|bool|float|double|var|{re.escape(func_name)})\s+{re.escape(func_name)}\s*\(")
    if lang in ("typescript", "tsx", "javascript", "jsx"):
        pats.append(rf"^\s*(?:export\s+|default\s+)*(?:class|interface|enum|type)\s+{kw}\b")
        pats.append(rf"^\s*(?:export\s+|default\s+)*(?:async\s+)?(?:function\s+)?{kw}\s*[\(<]")
        pats.append(rf"^\s*(?:export\s+|default\s+)?(?:const|let|var)\s+{kw}\s*[=:]")
    if lang == "go":
        pats.append(rf"^\s*(?:type\s+)?{kw}\s+(?:struct|interface)\b")
        pats.append(rf"^\s*func\s+(?:\([^)]*\)\s+)?{kw}\s*\(")
    if lang == "rust":
        pats.append(rf"^\s*(?:pub\s+)?(?:struct|enum|trait|impl\b.*?|fn)\s+{kw}\b")
        pats.append(rf"^\s*(?:pub\s+)?(?:async\s+)?fn\s+{kw}\s*[\(<]")
    if lang == "php":
        pats.append(rf"^\s*(?:public\s+|private\s+|protected\s+|static\s+|abstract\s+)*(?:class|interface|trait|enum)\s+{kw}\b")
        pats.append(rf"^\s*(?:public\s+|private\s+|protected\s+|static\s+)?function\s+{kw}\s*\(")
    if lang == "csharp":
        pats.append(rf"^\s*(?:public\s+|private\s+|protected\s+|internal\s+|static\s+|abstract\s+|sealed\s+|override\s+|virtual\s+)*(?:class|interface|struct|enum|record)\s+{kw}\b")
    if lang == "dart":
        pats.append(rf"^\s*(?:class|interface|enum|typedef)\s+{kw}\b")
        pats.append(rf"^\s*(?:Future\s*<[^>]*>\s*)?{kw}\s*\(")
    if lang == "swift":
        pats.append(rf"^\s*(?:public\s+|private\s+|internal\s+|fileprivate\s+|open\s+|static\s+)*(?:class|struct|enum|protocol|extension)\s+{kw}\b")
        pats.append(rf"^\s*(?:public\s+|private\s+|internal\s+|fileprivate\s+|open\s+|static\s+)?func\s+{kw}\s*\(")
    if lang == "scala":
        pats.append(rf"^\s*(?:class|object|trait|enum|case\s+class)\s+{kw}\b")
        pats.append(rf"^\s*def\s+{kw}\s*\(")
    if lang in ("c", "cpp", "hpp"):
        pats.append(rf"^\s*(?:class|struct|enum|union)\s+{kw}\b")
        func_name = name.split("(")[0].strip()
        pats.append(rf"^\s*(?:virtual\s+|static\s+|inline\s+)*(?:void|int|char|bool|float|double|long|short|unsigned|signed|auto|const|{re.escape(func_name)})\s+{kw}\s*\(")
    if lang == "kotlin":
        pats.append(rf"^\s*(?:class|interface|object|enum class|data class|sealed class)\s+{kw}\b")
        pats.append(rf"^\s*fun\s+{kw}\s*\(")

    # Generic fallback
    pats.append(rf"^\s*{kw}\s*(?:\(|<|:|\{{)")
    return pats


def _match_pattern(lines: List[str], patterns: List[str]) -> Optional[int]:
    for i, line in enumerate(lines):
        for p in patterns:
            if re.search(p, line):
                return i
    return None


def _indent_len(line: str) -> int:
    return len(line) - len(line.lstrip())


# ── end-keyword block (Ruby, Lua) ───────────────────────────────────────────

def _find_end_block(lines: List[str], name: str, lang: str) -> Tuple[Optional[int], Optional[int]]:
    if lang == "ruby":
        kw_pat = rf"^\s*(?:class|def|module)\s+{re.escape(name)}\b"
    else:
        kw_pat = rf"^\s*(?:function|def|class)\s+{re.escape(name)}\b"

    start = None
    for i, line in enumerate(lines):
        if re.search(kw_pat, line):
            start = i
            break
    if start is None:
        return None, None

    depth = 0
    for i in range(start, len(lines)):
        stripped = lines[i].strip()
        if lang == "ruby":
            if re.search(r"^\s*(?:class|def|module|if|unless|case|begin|do)\b", stripped):
                depth += 1
        else:  # lua
            if re.search(r"^\s*(?:function|do|if|for|while)\b", stripped):
                depth += 1
        if stripped == "end":
            depth -= 1
            if depth == 0:
                return start, i
    return start, len(lines) - 1


# ── Shell ───────────────────────────────────────────────────────────────────

def _find_shell_block(lines: List[str], name: str) -> Tuple[Optional[int], Optional[int]]:
    kw_pat = rf"^\s*(?:function\s+)?{re.escape(name)}\s*\(\)"
    start = None
    for i, line in enumerate(lines):
        if re.search(kw_pat, line):
            start = i
            break
    if start is None:
        return None, None

    for i in range(start + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped and not stripped.startswith("#") and _indent_len(lines[i]) == 0 and not stripped.endswith("\\"):
            # Top-level non-continuation line = end of function
            return start, i - 1 if i > start else start
    return start, len(lines) - 1


# ── extract_imports ─────────────────────────────────────────────────────────

def extract_imports(file_path: str) -> List[ImportInfo]:
    """Extract import statements from source file. Supports 12+ languages."""
    ext = os.path.splitext(file_path)[1].lower()
    lang = EXT_LANG.get(ext)
    if lang is None:
        return []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return []

    # Remove comments for cleaner parsing
    clean = _strip_comments(text, lang)

    if lang == "python":
        return _parse_python_imports(clean)
    if lang in ("typescript", "tsx", "javascript", "jsx"):
        return _parse_ts_imports(clean)
    if lang == "go":
        return _parse_go_imports(clean)
    if lang == "rust":
        return _parse_rust_imports(clean)
    if lang == "java":
        return _parse_java_imports(clean)
    if lang in ("c", "cpp", "hpp"):
        return _parse_cpp_imports(clean)
    if lang == "csharp":
        return _parse_csharp_imports(clean)
    if lang in ("kotlin", "scala"):
        return _parse_kotlin_imports(clean)
    if lang == "php":
        return _parse_php_imports(clean)
    if lang == "ruby":
        return _parse_ruby_imports(clean)
    if lang == "dart":
        return _parse_ts_imports(clean)  # Dart uses similar import syntax

    return []


def _strip_comments(text: str, lang: str) -> str:
    """Remove line comments for import parsing."""
    if lang in ("python", "ruby", "shell", "perl"):
        return re.sub(r"#.*$", "", text, flags=re.MULTILINE)
    if lang in ("typescript", "tsx", "javascript", "jsx", "java", "go", "rust",
                "c", "cpp", "hpp", "csharp", "kotlin", "swift", "dart", "scala", "php"):
        # Remove // and /* */ comments
        text = re.sub(r"//.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        return text
    if lang == "lua":
        text = re.sub(r"--.*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"--\[\[.*?\]\]", "", text, flags=re.DOTALL)
        return text
    return text


def _parse_python_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*import\s+(\S+)", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[], is_relative=False))
    for m in re.finditer(r"^\s*from\s+(\S+)\s+import\s+(.+)", text, re.MULTILINE):
        names = [n.strip().split(" as ")[0] for n in m.group(2).split(",")]
        is_rel = m.group(1).startswith(".")
        imports.append(ImportInfo(source_module=m.group(1), imported_names=names, is_relative=is_rel))
    return imports


def _parse_ts_imports(text: str) -> List[ImportInfo]:
    imports = []
    # ESM import { x } from "y"
    for m in re.finditer(r'import\s+(?:\{[^}]*\}|\*\s+as\s+\w+|\w+)\s+from\s+["\']([^"\']+)["\']', text):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[], is_relative=m.group(1).startswith(("./", "../"))))
    # import "y"
    for m in re.finditer(r'^\s*import\s+["\']([^"\']+)["\']', text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[], is_relative=m.group(1).startswith(("./", "../"))))
    # require("y")
    for m in re.finditer(r'(?:const|let|var)\s+\w+\s*=\s*require\s*\(\s*["\']([^"\']+)["\']', text):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[], is_relative=m.group(1).startswith(("./", "../"))))
    return imports


def _parse_go_imports(text: str) -> List[ImportInfo]:
    imports = []
    # Single: import "x"
    for m in re.finditer(r'^\s*import\s+["\']([^"\']+)["\']', text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    # Grouped: import ( "x" "y" )
    group = re.search(r"import\s+\(([^)]*)\)", text, re.DOTALL)
    if group:
        for m in re.finditer(r'["\']([^"\']+)["\']', group.group(1)):
            imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    return imports


def _parse_rust_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*use\s+(.+);", text, re.MULTILINE):
        path = m.group(1).split("::")[0]
        imports.append(ImportInfo(source_module=path, imported_names=[m.group(1)], is_relative=path == "self" or path == "super" or path == "crate"))
    return imports


def _parse_java_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*import\s+(?:static\s+)?(\S+);", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    return imports


def _parse_cpp_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r'^\s*#\s*include\s+[<"]([^>"]+)[">]', text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    return imports


def _parse_csharp_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*using\s+(\S+);", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    return imports


def _parse_kotlin_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*import\s+(\S+)", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    return imports


def _parse_php_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*use\s+(\S+)", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    for m in re.finditer(r"(?:require|include)(?:_once)?\s*\(?\s*['\"]([^'\"]+)['\"]", text):
        imports.append(ImportInfo(source_module=m.group(1), imported_names=[]))
    return imports


def _parse_ruby_imports(text: str) -> List[ImportInfo]:
    imports = []
    for m in re.finditer(r"^\s*require\s+(.+)$", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1).strip().strip('"\''), imported_names=[]))
    for m in re.finditer(r"^\s*require_relative\s+(.+)$", text, re.MULTILINE):
        imports.append(ImportInfo(source_module=m.group(1).strip().strip('"\''), imported_names=[], is_relative=True))
    return imports


# ── structure_hash (fingerprint) ────────────────────────────────────────────

def structure_hash(file_path: str) -> str:
    """
    Compute a structural fingerprint (SHA-256) of a source file.
    Strips whitespace-only lines and normalizes indentation so that cosmetic
    changes (reformatting, comment changes) produce the same hash.
    """
    try:
        with open(file_path, "rb") as f:
            raw = f.read()
    except Exception:
        return ""

    body = raw.decode("utf-8", errors="replace")

    # Remove comments
    ext = os.path.splitext(file_path)[1].lower()
    lang = EXT_LANG.get(ext)
    if lang:
        body = _strip_comments(body, lang)

    # Normalize: strip blank lines, collapse whitespace
    lines = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Normalize indentation to 2-space
        indent = _indent_len(line)
        lines.append("  " * (indent // 2 if indent > 0 else 0) + stripped)

    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def content_hash(file_path: str) -> str:
    """Raw SHA-256 of file content — detects any change."""
    try:
        with open(file_path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return ""


# ── classify_change ─────────────────────────────────────────────────────────

def classify_change(file_path: str, old_structure_hash: str) -> str:
    """
    Classify a change as:
      "none"       — file unchanged (content hash matches baseline)
      "cosmetic"   — structure unchanged (comments/whitespace only)
      "structural" — actual code change detected
    Returns baseline structure_hash if file doesn't exist (for new files).
    """
    if not os.path.exists(file_path):
        return "new"

    new_ch = content_hash(file_path)
    if new_ch == old_structure_hash:
        return "none"
    if old_structure_hash and new_ch != structure_hash(file_path):
        return "cosmetic"
    return "structural"


# ── function-level fingerprinting ──────────────────────────────────────────

def function_fingerprints(file_path: str) -> Dict[str, str]:
    """Compute per-function/class fingerprints.

    Returns dict of {function_name: sha256_of_block_content}.
    Uses find_block to locate each named function/class, then hashes its body.
    """
    ext = os.path.splitext(file_path)[1].lower()
    lang = EXT_LANG.get(ext)
    if lang is None:
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return {}

    name_patterns = {
        "python": r"^\s*(?:class|def|async def)\s+(\w+)",
        "typescript": r"^\s*(?:export\s+|default\s+)*(?:function|class|interface|enum|type)\s+(\w+)",
        "javascript": r"^\s*(?:export\s+|default\s+)*(?:function|class)\s+(\w+)",
        "go": r"^\s*func\s+(?:\([^)]*\)\s+)?(\w+)",
        "rust": r"^\s*(?:pub\s+)?(?:fn|struct|enum|trait)\s+(\w+)",
        "java": r"^\s*(?:\w+\s+)*(?:class|interface|enum)\s+(\w+)",
    }

    pat = name_patterns.get(lang)
    if pat is None:
        if lang in ("c", "cpp", "hpp", "h"):
            pat = r"^\s*(?:typedef\s+)?(?:struct|class|enum|union)\s+(\w+)"
        elif lang in ("cs", "kt", "swift", "dart", "scala", "php", "ruby", "lua"):
            pat = r"^\s*(?:\w+\s+)*(?:class|struct|enum|interface|fn|func|fun|def|function)\s+(\w+)"
        else:
            return {}

    names = set()
    for line in lines:
        m = re.search(pat, line)
        if m:
            names.add(m.group(1))

    # Additional pass for C: extract function names
    if lang in ("c", "cpp", "hpp", "h"):
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", "/*", "*")):
                continue
            # Skip obvious non-definitions
            if any(stripped.startswith(kw) for kw in
                   ["if ", "while ", "for ", "switch ", "return ", "else ", "do ",
                    "case ", "break ", "continue ", "goto ", "#"]):
                continue
            # Match identifier( — function definitions
            # Skip lines with =, ; before ( (variable declarations)
            if "(" not in stripped:
                continue
            before_paren = stripped.split("(")[0].strip()
            if not before_paren:
                continue
            # Get last word before (
            words = before_paren.split()
            if not words:
                continue
            name = words[-1].rstrip("*")
            if not name or not name[0].isalpha():
                continue
            # Filter out keywords and type names
            if name in ("if", "while", "for", "switch", "return", "sizeof", "else",
                        "do", "case", "break", "continue", "goto", "typedef", "extern",
                        "static", "inline", "const", "volatile", "unsigned", "signed",
                        "void", "int", "char", "long", "short", "float", "double",
                        "struct", "union", "enum", "auto", "register", "extern",
                        "typeof", "size_t", "int8_t", "int16_t", "int32_t", "int64_t",
                        "uint8_t", "uint16_t", "uint32_t", "uint64_t"):
                continue
            # Skip if it's a variable declaration (has = or ;)
            if "=" in before_paren and ")" not in before_paren:
                continue
            names.add(name)

    fps = {}
    for name in names:
        start, end = find_block(file_path, name)
        if start is not None and end is not None:
            block_text = "".join(lines[start:end + 1])
            h = hashlib.sha256(block_text.encode("utf-8")).hexdigest()
            fps[name] = h

    return fps


# ── extract_struct_fields ──────────────────────────────────────────

@dataclass
class StructField:
    name: str
    type_name: str = ""


def extract_struct_fields(file_path: str) -> Dict[str, List[StructField]]:
    """Extract struct/class definitions with their fields.

    Supports C (struct), Python (class with annotations), Java/C#/TS (class fields).
    Returns { struct_name: [StructField(name, type_name), ...], ... }
    """
    ext = os.path.splitext(file_path)[1].lower()
    lang = EXT_LANG.get(ext)
    if lang is None:
        return {}

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception:
        return {}

    if lang == "python":
        return _extract_python_fields(source)

    if lang in BRACE_LANGS:
        return _extract_brace_fields(source, lang)

    return {}


def _extract_python_fields(source: str) -> Dict[str, List[StructField]]:
    """Extract class fields using Python AST."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}

    result: Dict[str, List[StructField]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        fields: List[StructField] = []
        seen = set()
        for item in ast.iter_child_nodes(node):
            # Instance variable assignment: self.x = ...
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                for stmt in ast.walk(item):
                    if isinstance(stmt, ast.Assign):
                        for target in stmt.targets:
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == "self":
                                if target.attr not in seen:
                                    seen.add(target.attr)
                                    type_hint = ""
                                    fields.append(StructField(name=target.attr, type_name=type_hint))
            # Class-level annotation: x: int = 0
            if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                if item.target.id not in seen:
                    seen.add(item.target.id)
                    type_hint = _ast_to_type_str(item.annotation) if item.annotation else ""
                    fields.append(StructField(name=item.target.id, type_name=type_hint))
        if fields:
            result[node.name] = fields
    return result


def _ast_to_type_str(annotation: ast.expr) -> str:
    """Convert an AST type annotation to a readable string."""
    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Subscript):
        base = _ast_to_type_str(annotation.value)
        slc = _ast_to_type_str(annotation.slice) if hasattr(annotation, 'slice') else ""
        return f"{base}[{slc}]"
    if isinstance(annotation, ast.Attribute):
        return f"{_ast_to_type_str(annotation.value)}.{annotation.attr}"
    if isinstance(annotation, ast.Constant):
        return str(annotation.value)
    if isinstance(annotation, ast.Tuple):
        return ", ".join(_ast_to_type_str(e) for e in annotation.elts)
    if isinstance(annotation, ast.Index):
        return _ast_to_type_str(annotation.value)
    return ""


def _extract_brace_fields(source: str, lang: str) -> Dict[str, List[StructField]]:
    """Extract struct/class fields from brace-delimited languages."""
    # Strip string/comment content to avoid false matches
    clean_source = _strip_comments(source, lang)
    lines = clean_source.splitlines()

    struct_re = _struct_pattern(lang)
    if struct_re is None:
        return {}

    result: Dict[str, List[StructField]] = {}
    i = 0
    while i < len(lines):
        m = re.search(struct_re, lines[i])
        if not m:
            i += 1
            continue
        struct_name = m.group(1)
        # Find opening brace
        brace_start = lines[i].find("{")
        if brace_start == -1:
            i += 1
            continue
        brace_depth = 1
        fields: List[StructField] = []
        field_lines: List[str] = []
        j = i + 1
        while j < len(lines) and brace_depth > 0:
            line = lines[j]
            for ch in line:
                if ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
            if brace_depth == 1:
                field_lines.append(line)
            elif brace_depth == 0 and field_lines:
                # Extract field type/name from collected lines in this struct
                for fl in field_lines:
                    fl_stripped = fl.strip()
                    if not fl_stripped:
                        continue
                    # Skip access specifiers, methods, comments
                    if fl_stripped.startswith(("public:", "private:", "protected:",
                                                "//", "/*", "*", "#")):
                        continue
                    # Skip lines that look like methods (have parentheses)
                    if "(" in fl_stripped and ")" in fl_stripped:
                        continue
                    # Parse: optional modifiers + type + name
                    f = _parse_c_field(fl_stripped)
                    if f:
                        fields.append(f)
            j += 1

        if fields:
            result[struct_name] = fields
        i = j if j > i else i + 1

    return result


def _struct_pattern(lang: str) -> Optional[str]:
    """Get regex pattern for struct/class declaration header."""
    c_like = {"c", "cpp", "hpp", "h", "cs", "java", "dart", "swift", "scala", "kotlin"}
    ts_like = {"typescript", "tsx", "javascript", "jsx"}
    go_rust = {"go", "rust"}

    if lang in c_like:
        return r"(?:typedef\s+)?(?:struct|class|union)\s+(\w+)"
    if lang in ts_like:
        return r"(?:export\s+|default\s+)?(?:class|interface|type)\s+(\w+)"
    if lang == "go":
        return r"(?:type\s+)?(\w+)\s+(?:struct|interface)\b"
    if lang == "rust":
        return r"(?:pub\s+)?(?:struct|enum|trait)\s+(\w+)"
    return None


def _parse_c_field(line: str) -> Optional[StructField]:
    """Parse a C-like field declaration: 'type name;' or 'type name[N];'"""
    # Remove trailing semicolon/braces
    line = line.strip().rstrip(";").strip()
    if not line:
        return None
    # Skip if it looks like a preprocessor directive, comment, or empty
    if line.startswith(("#", "//", "/*", "*", "typedef", "using")):
        return None
    # Remove leading modifiers
    for mod in ["static ", "const ", "volatile ", "extern ", "inline ",
                "unsigned ", "signed ", "long ", "short "]:
        if line.startswith(mod):
            line = line[len(mod):]
    # Remove trailing array notation: name[16] → name
    m = re.match(r"(.+?)\s+(\w+)\s*(?:\[[^\]]*\])?\s*$", line)
    if not m:
        # Try bitfield: name : N
        m = re.match(r"(.+?)\s+(\w+)\s*:\s*\d+\s*$", line)
    if m:
        type_name = m.group(1).strip()
        field_name = m.group(2).strip()
        # Skip if it's still a modifier or type keyword
        if field_name.lower() in ("struct", "union", "enum", "typedef", "class"):
            return None
        return StructField(name=field_name, type_name=type_name)
    return None


def compare_function_fingerprints(old_fps: Dict[str, str],
                                   new_fps: Dict[str, str]) -> Dict[str, str]:
    """Compare two function fingerprint dicts.

    Returns: {function_name: "unchanged" | "modified" | "added" | "removed"}
    """
    result: Dict[str, str] = {}
    all_names = set(old_fps.keys()) | set(new_fps.keys())
    for name in all_names:
        if name not in old_fps:
            result[name] = "added"
        elif name not in new_fps:
            result[name] = "removed"
        elif old_fps[name] != new_fps[name]:
            result[name] = "modified"
        else:
            result[name] = "unchanged"
    return result
