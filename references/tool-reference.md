# Tool Reference — Python 脚本详细用法

本文档详细描述 `scripts/` 下每个工具的用法、命令行参数、行为细节和输出格式。

---

## `layout_generator.py` — YAML → drawio XML

直接生成图表的核心工具。读取 YAML 结构定义，计算布局（节点坐标、group 大小、边路由），输出 `.drawio` XML。

### 用法

```bash
# 基本用法
python3 scripts/layout_generator.py --input structure.yaml --output diagram.drawio

# 从 stdin 读取（便于和其他命令管道）
cat structure.yaml | python3 scripts/layout_generator.py --stdin --output diagram.drawio
```

### 输入 YAML 格式

参见 `references/structured-output-format.md`。关键字段：

| 字段 | 说明 |
|------|------|
| `nodes[].container` | `true` = 泳道容器，子文本行自动堆叠 |
| `nodes[].members` | 容器内子文本行（纯展示，不写 path/lines） |
| `nodes[].scale` | 语义权重，1.0=普通，1.5=更大，0.7=更小 |
| `notes` | 注释框（`shape=note` + `autosizeText=1`），自动放置 group 底部 |
| `layout.algorithm` | 布局算法：layered / grid / hub / flow / tree / preserve |
| `layout.preserve_existing` | `true` 时保持已有节点坐标 |

### 自动处理

- **容器节点**：`swimlane` + `childLayout=stackLayout` + `autosizeText=1`
- **注释框**：自动放置在 group 底部，不覆盖节点
- **边路由**：障碍物感知（20px clearance），L 形/Z 形正交折线
- **路径**：自动加一层 `../` 适配 vscode-drawio 的 `path.join` 特性
- **Group 大小**：自动根据容器节点高度扩展
- **输出尺寸**：自动根据内容扩展

---

## `incremental_reader.py` — 代码变更 → 图增量更新

### 用法

```bash
# 指纹检测（默认）
python3 scripts/incremental_reader.py --project-root . --existing diagram.drawio --diff

# Git diff 模式（工程项目推荐）
python3 scripts/incremental_reader.py --project-root . --existing diagram.drawio --git-diff

# 指定 diff ref（默认 HEAD）
python3 scripts/incremental_reader.py --project-root . --existing diagram.drawio --git-diff --git-ref HEAD~3

# 应用 patch
python3 scripts/incremental_reader.py --patch patch.yaml --existing diagram.drawio --output diagram.drawio
```

### `--git-diff` 模式 vs `--diff` 模式

| 维度 | `--diff` | `--git-diff` |
|------|----------|-------------|
| 检测方式 | SHA-256 指纹对比 | `git diff` 精确行级 diff |
| AI 能看懂的 | "文件变了" | "+ function divide(self, a, b):" |
| 变更分类 | none/cosmetic/structural | 基于 diff 内容的关键词检测 |
| drawio 变更 | 无 | 解析 XML diff → 新增/删除节点和边 |
| 需要 git | 否 | 是 |
| 工程项目推荐 | ❌ | ✅ |

### 参数

| 参数 | 说明 |
|------|------|
| `--project-root`, `-p` | 项目根目录 |
| `--existing`, `-e` | 现有的 `.drawio` 文件（基线） |
| `--diff` | 输出变更报告 |
| `--patch` | 应用 patch YAML 文件 |
| `--output`, `-o` | 输出路径 |
| `--auto` | 一键：扫描 → 生成 patch → 应用 |
| `--include` | 文件包含模式（默认包含 20+ 代码和非代码类型） |
| `--exclude` | 文件排除模式 |
| `--no-index` | 跳过索引更新 |

### 文件扫描策略

使用 **`git ls-files`**（自动识别 `.gitignore`，比 `os.walk` 快 10 倍）。
非 git 项目自动回退到 `os.walk`。

**默认包含的文件类型：**

| 类别 | 扩展名/文件名 |
|------|-------------|
| 代码 | `.ts`, `.js`, `.py`, `.java`, `.go`, `.rs`, `.rb`, `.tsx`, `.jsx`, `.php`, `.c`, `.cpp`, `.h`, `.cs`, `.kt`, `.swift`, `.dart`, `.scala`, `.lua`, `.sh` |
| 容器/构建 | `Dockerfile*`, `Makefile*` |
| CI/CD | `.yml`, `.yaml`（自动识别 workflow/CI） |
| 配置 | `.json`, `.toml`, `.cfg`, `.conf`, `.ini` |
| 数据 | `.sql`, `.graphql` |

### 变更检测逻辑

使用 SHA-256 指纹（非 mtime）检测变更：

| 变更类型 | 含义 | trigger |
|----------|------|---------|
| `new` | 新增文件 | 指纹 map 中不存在 |
| `deleted` | 文件被删 | 指纹 map 中存在但文件不存在 |
| `structural` | 代码逻辑变了 | 内容指纹 AND 结构指纹都变 |
| `cosmetic` | 只改了注释/格式 | 内容指纹变但结构指纹不变 |
| `none` | 未变 | 内容指纹一致 |

### 输出格式（--diff）

```yaml
new_files:
  - path: ../src/services/payment.ts
    type: service
    lines: 150
modified_files:
  - path: ../src/services/user.ts
    old_lines: 120   # 旧文件行数
    new_lines: 150   # 新文件行数
deleted_files:
  - ../src/services/old_auth.ts
orphaned_nodes:
  - id: old_auth
    label: AuthMiddleware
    path: ../src/services/old_auth.ts
suggested_edges:     # 基于 import 图自动建议
  - from: report_svc
    to: format_out
    label: depends on
    style: dashed
```

### 执行流程（--patch）

1. 加载现有 `.drawio` 作为基线
2. 合并 patch（添加/删除/更新节点和边）
3. 调用 `layout_generator.py` 计算布局（`preserve_existing: true` 时保留未变节点坐标）
4. 验证布局（重叠、越界）
5. 输出 `.drawio`
6. 自动更新 `.vscode/drawio-code-links.json`

---

## `incremental_writer.py` — 图变更 → 代码骨架

### 用法

```bash
# 检测差异
python3 scripts/incremental_writer.py --drawio diagram.drawio --project-root . --diff

# 应用 scaffold
python3 scripts/incremental_writer.py --plan scaffold.yaml --apply

# 一键模式
python3 scripts/incremental_writer.py --drawio diagram.drawio --project-root . --auto
```

### 参数

| 参数 | 说明 |
|------|------|
| `--drawio`, `-d` | 源 `.drawio` 文件 |
| `--project-root`, `-p` | 项目根目录 |
| `--diff` | 输出差异报告 |
| `--plan` | scaffold YAML 文件 |
| `--apply` | 执行 scaffold |
| `--auto` | 一键模式 |
| `--output`, `-o` | 输出 scaffold YAML |

### 智能合并行为

`create_files` 的行为取决于文件是否存在：

| 场景 | 行为 |
|------|------|
| **文件不存在** | 创建占位文件（import + class + method stub） |
| **文件已存在** | **智能合并**：注入新 import（去重）+ 追加方法 stub（用 `find_block` 定位 class 底部插入），不覆盖已有代码 |

修改前自动生成 `.bak` 备份，位置在原文件同目录。

---

## `code_sync.py` — 行号同步

### 用法

```bash
# 更新所有节点的行号
python3 scripts/code_sync.py --drawio diagram.drawio --project-root . --update-lines --sync

# 预览（dry-run，不写入）
python3 scripts/code_sync.py --drawio diagram.drawio --project-root . --update-lines

# 只同步特定节点
python3 scripts/code_sync.py --drawio diagram.drawio --project-root . --nodes scheduler,allocproc --sync
```

### 参数

| 参数 | 说明 |
|------|------|
| `--drawio`, `-d` | drawio 文件路径 |
| `--project-root`, `-p` | 项目根目录 |
| `--sync` | 应用变更（不加则 dry-run） |
| `--update-lines` | 更新行号（默认 true，用 `--no-update-lines` 禁用） |
| `--nodes` | 逗号分隔的节点 ID 列表（默认全部） |
| `--no-index` | 跳过索引更新 |

### 行号查找策略

1. 读取节点的 `path` 对应的文件
2. 用 `analyzer.py` 的 `find_block()` 查找节点 label 对应的类/函数定义
3. 更新 `hedietLinkedDataV1_start_line_x-num` / `hedietLinkedDataV1_end_line_x-num`
4. 如果找不到匹配（如 label 是 "contains"），记录错误但不修改

---

## `analyzer.py` — 代码块查找 + 函数级指纹（15+ 语言）

### 用法

```python
from scripts.analyzer import find_block, extract_imports, structure_hash, function_fingerprints, compare_function_fingerprints

# 查找类/函数的行号范围（返回 0-indexed [start, end]）
start, end = find_block("src/myapp.py", "Calculator")

# 提取 import 依赖
imports = extract_imports("src/services/report_service.py")

# 计算结构指纹
hash = structure_hash("src/main.py")

# 函数级指纹（比文件级指纹更精确）
fps = function_fingerprints("src/main.py")
# 返回 {function_name: sha256_of_block}

# 对比两个版本的函数指纹
diff = compare_function_fingerprints(old_fps, new_fps)
# 返回 {function_name: "unchanged" | "modified" | "added" | "removed"}
```

### 支持的语言

| 扩展名 | 语言 | 方法 |
|--------|------|------|
| `.py` | Python | AST（精确）+ 缩进 fallback |
| `.ts`, `.tsx`, `.js`, `.jsx` | JS/TS | 大括号匹配（字符串/正则感知） |
| `.java` | Java | 同上 |
| `.go` | Go | 同上 |
| `.rs` | Rust | 同上 |
| `.c`, `.cpp`, `.h`, `.hpp` | C/C++ | 同上 |
| `.cs` | C# | 同上 |
| `.kt`, `.kts` | Kotlin | 同上 |
| `.swift` | Swift | 同上 |
| `.dart` | Dart | 同上 |
| `.scala` | Scala | 同上 |
| `.php` | PHP | 同上 |
| `.rb` | Ruby | end 关键字匹配 |
| `.lua` | Lua | end 关键字匹配 |
| `.sh`, `.bash`, `.zsh` | Shell | 缩进匹配 |

### 大括号匹配改进

- **字符串感知**：`"{"` 和 `'}'` 在字符串内不计入
- **模板字面量**：`` `hello ${name}` `` 中的 `${}` 正确处理
- **正则感知**：JS/TS 的 `/regex/` 字面量正确处理

---

## `import_graph.py` — Import 依赖图

### 用法

```python
from scripts.import_graph import build_import_graph, suggest_edges

# 构建 import 图
graph = build_import_graph(project_root, file_paths)

# 建议边
edges = suggest_edges(graph, existing_nodes)
```

通常被 `incremental_reader --diff` 自动调用，不直接使用。

### 支持的 import 语法

| 语言 | import 语法 |
|------|------------|
| Python | `import x` / `from x import y` / 目录自动补 `__init__.py` |
| JS/TS | `import {x} from 'y'` / `require('y')` / 目录自动补 `index.ts` |
| Go | `import "x"` |
| Rust | `use x::y;` / 目录自动补 `mod.rs` |
| Java | `import x.y;` |
| C/C++ | `#include "x"` — 自动尝试 `kernel/` `src/` `include/` `lib/` 前缀 |
| C# | `using x;` |
| PHP | `use x;` / `require 'x'` |
| Ruby | `require 'x'` |

---

## `index_generator.py` — VS Code 索引

### 用法

```bash
# 扫描单个 drawio 文件
python3 scripts/index_generator.py --drawio diagrams/arch.drawio

# 扫描整个 workspace 中所有 drawio 文件
python3 scripts/index_generator.py --workspace .

# 预览模式
python3 scripts/index_generator.py --workspace . --dry-run
```

通常被 `incremental_reader.py` 和 `code_sync.py` 自动调用。输出 `.vscode/drawio-code-links.json`。

---

## `layout_analyzer.py` — 布局验证

### 用法

```bash
# 分析布局
python3 scripts/layout_analyzer.py --drawio diagram.drawio

# 检查重叠
python3 scripts/layout_analyzer.py --drawio diagram.drawio --check-overlaps

# 自动优化布局
python3 scripts/layout_analyzer.py --drawio diagram.drawio --optimize --algorithm force-directed

# 输出 JSON 报告
python3 scripts/layout_analyzer.py --drawio diagram.drawio --output report.json --verbose
```

### 检测内容

- 节点重叠
- 边穿过节点
- 节点越界
- 布局密度过高

---

## `git_diff_reader.py` — Git diff 封装 + drawio XML diff

被 `incremental_reader --git-diff` 自动调用，通常不直接使用。

### 提供的能力

```python
from scripts.git_diff_reader import *

# 检测 git 仓库
is_git_repo(project_root)  # → bool

# 更改的文件列表
changed_files(ref="HEAD", project_root=".")  # → ["src/a.py", "src/b.ts"]

# 文件级 diff
file_diff("src/a.py", "HEAD")        # → unified diff string
parse_git_diff(diff_str)             # → [{"type":"add","content":"..."}]

# Diff 语义分类
classify_change_from_diff(diff_str)  # → "structural" | "cosmetic" | "none"

# AI 可读的 diff 摘要
code_diff_summary("src/a.py", "HEAD")  # → markdown 格式的变更摘要

# Drawio XML diff（对比两个版本的 drawio 文件）
drawio_diff("diagrams/arch.drawio", "HEAD")
# → DrawioDiff with added/removed/modified nodes and edges

# 安全分支
safe_branch(project_root)    # → branch name, 自动 checkout 安全分支
commit_and_return(project_root, "msg")  # → commit 并切回原分支

# 脏工作区检测
check_dirty(project_root)   # → bool
```

### 基本用法

```bash
# 导出 PNG
python3 scripts/export_diagram.py --input diagram.drawio --format png --scale 2

# 预览（--preview 时不加 -e 标志）
python3 scripts/export_diagram.py --input diagram.drawio --format png --preview

# SVG / PDF
python3 scripts/export_diagram.py --input diagram.drawio --format svg
python3 scripts/export_diagram.py --input diagram.drawio --format pdf

# 浏览器 URL（无需 CLI）
python3 scripts/export_diagram.py --input diagram.drawio --browser-fallback
```

### 自动处理

- 自动检测 draw.io CLI
- 自动修复 PNG（IEND chunk 补齐）
- CLI 不可用时自动 fallback 到浏览器 URL
