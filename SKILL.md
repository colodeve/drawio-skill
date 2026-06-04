---
name: drawio-architect
version: 2.2.0
description: |
  Incremental draw.io architecture diagram generation and management. Links every diagram element to source code lines via hedietLinkedDataV1 for VS Code double-click jump-to-code. Three workflows: (1) Incremental Read — auto-update diagrams from code changes using git ls-files scanning, function-level SHA-256 fingerprint diff detection, import graph edge suggestion, and non-code file support (Dockerfile, Makefile, CI YAML, configs, SQL); (2) Incremental Write — scaffold code from diagram changes with smart merge (append imports/methods, never overwrite); (3) Direct Generation — from YAML to drawio XML with automatic layout, obstacle-aware edge routing, container nodes with members, and autosize notes. The AI never writes XML — it outputs structured YAML, Python scripts compute layout and generate XML. Use this skill whenever the user mentions architecture diagrams, drawio, draw.io, code-to-diagram, diagram-to-code, architecture visualization, system design diagrams, or wants to visualize code structure or design new modules visually.
license: MIT
compatibility: Requires Python 3.8+. Optional draw.io CLI for PNG export.
platforms: [macos, linux, windows]
---

# Draw.io Architect

drawio文件画架构图，并同步架构图和代码，**绝不手写 XML**——输出结构化 YAML，Python 脚本自动计算布局、边路由、坐标。

---

## 工作流选择

| 用户意图 | 工作流 | 详细参考 |
|---|---|---|
| "从代码生成图" / "代码变了更新图" | **增量读取** | `references/incremental-workflows.md` — Step 1-6 |
| "基于 git diff 精准检测代码变更" | **git-diff 模式** | `scripts/incremental_reader.py --git-diff` |
| "设计新模块" / "从图表生成代码" | **增量写入** | `references/incremental-workflows.md` — 下半部分 |
| "把这个 YAML 画成图" | **直接生成** | `scripts/layout_generator.py --input --output` |
| "换个样式/颜色" | 样式预设 | `references/style-presets.md` |
| "导出 PNG/SVG" | 导出 | `references/export-commands.md` |

> **不知道先读什么？** 先读 `references/incremental-workflows.md`，它覆盖了最常用的两种场景。

---

## YAML 输出格式

```yaml
nodes:
  - id: scheduler
    label: scheduler()
    type: controller
    group: proc_mgmt
    path: ../kernel/proc.c
    lines: [424, 691]        # 0-indexed
    container: true
    members:
      - "Round-robin: iterates proc[]"
      - "Calls swtch() to context-switch"
    scale: 1.0                # 1.0=普通，1.5=突出，0.7=紧凑

notes:
  - text: "自动缩放文字"
    group: proc_mgmt
    width: 200
    height: 80

edges:
  - from: scheduler
    to: allocproc
    label: swtch
    style: dashed

layout:
  algorithm: layered
  direction: top-to-bottom
  preserve_existing: true
```

**完整格式规范** → `references/structured-output-format.md`
**布局算法详解** → `references/layout-system.md`

---

## 路径计算规则

vscode-drawio 使用 `path.join(drawioFilePath, path)` 解析路径，文件名也算一个路径段。

| drawio 位置 | 代码位置 | path |
|---|---|---|
| `根目录/arch.drawio` | `src/app.ts` | `../src/app.ts` |
| `diagrams/arch.drawio` | `src/app.ts` | `../../src/app.ts` |

> 脚本的 `_fix_hediet_path()` 写入 XML 时会自动处理。但 YAML 中仍需按此规则填写。

> **运行脚本时**：本 skill 安装于 `~/.opencode/skills/drawio-skill-enhanced/`。使用 `python3 <skill-path>/scripts/<script>.py` 运行，或用相对路径 `scripts/<script>.py`（需在 skill 目录下执行）。所有脚本的 import 路径已自动处理。

---

## 多语言支持

节点上的显示文本（label、members、notes.text、group label）可以跟随用户使用的语言。
但标识性字段必须保持英文/数字，不随语言变化。

### 可本地化（根据用户语言翻译）

| 字段 | 说明 |
|------|------|
| `nodes[].label` | 节点显示名 |
| `nodes[].members` | 容器内子文本行 |
| `nodes[].description` | 描述 |
| `notes[].text` | 注释框内容 |
| `groups[].label` | 泳道标题 |
| `edges[].label` | 边标签 |

### 保持英文（不翻译）

| 字段 | 理由 |
|------|------|
| `id` | 被 `from`/`to` 引用，必须全局稳定 |
| `path` | 文件系统路径，必须匹配实际路径 |
| `lines` | 行号，数字与语言无关 |
| `type` | 映射到 draw.io 颜色/形状的标识符 |
| `container`, `scale` | 布尔值/数值 |
| `from`, `to` | 边引用节点 ID |
| `style` | `solid`/`dashed` |
| `layout.*` | 算法名、间距 |
| `action` | `create`/`patch`/`scaffold` |

### 示例

```yaml
nodes:
  - id: user_svc          # 保持英文
    label: 用户服务        # 翻译
    type: service          # 保持英文
    path: ../src/svc.ts    # 保持英文
    lines: [0, 119]        # 保持数字
```

### 原理

draw.io XML 中的 `label`/`value` 只影响画布上显示的文本，不影响功能。
`path` 和 `lines` 由 vscode-drawio 扩展的 `CodePosition.deserialize()` 解析，需要精确匹配文件系统和 0-indexed 行号。
`id` 被 `edges[].from/to` 引用，必须全局稳定。

---

## 类型颜色映射

| type | 颜色 | 形状 | 适用文件 |
|---|---|---|---|
| `entry`, `config` | 橙 | rounded | main、index、配置文件 |
| `service`, `logic` | 蓝 | rounded | 业务逻辑、服务类 |
| `data`, `model`, `database` | 绿 | cylinder | 数据模型、SQL、GraphQL |
| `external`, `api` | 红 | hexagon | 外部 API、第三方 |
| `controller`, `ui` | 紫 | rounded | 控制器、UI 组件 |
| `infrastructure`, `middleware` | 靛 | rounded | Dockerfile、Makefile、CI 配置 |
| `gateway` | 金 | rounded | 网关 |
| `queue` | 黄 | rounded | 消息队列 |
| `decision` | 橙 | rhombus | 判断节点 |

只写 `type`，脚本自动映射颜色和形状。

---

## 脚本工具参考

| 脚本 | 用途 | 详细参考 |
|---|---|---|
| `incremental_reader.py` | 扫描代码变更，增量更新图。支持 `--diff`（指纹）和 `--git-diff`（git 精确 diff）两种模式 | `references/tool-reference.md` + `references/incremental-workflows.md` |
| `git_diff_reader.py` | git diff 封装 + drawio XML diff 解析，被 `--git-diff` 自动调用 | `references/tool-reference.md` |
| `incremental_writer.py` | 从图生成/更新代码骨架（智能合并） | `references/tool-reference.md` + `references/incremental-workflows.md` |
| `layout_generator.py` | YAML → drawio XML（布局+边路由+容器节点） | `references/tool-reference.md` |
| `analyzer.py` | 代码块查找 + 函数级指纹（15+ 语言） | `references/tool-reference.md` |
| `import_graph.py` | import 依赖图分析（自动被 `--diff` 调用） | `references/tool-reference.md` |
| `code_sync.py` | 同步图中的行号 | `references/tool-reference.md` |
| `export_diagram.py` | 导出 PNG/SVG/PDF | `references/export-commands.md` |
| `index_generator.py` | 刷新 `.vscode/drawio-code-links.json` | 自动调用 |
| `layout_analyzer.py` | 布局验证 | `references/tool-reference.md` |

---

## 关键提醒

- **不要手写 XML** → 永远输出 YAML
- **路径规则** → 比直觉多一层 `../`
- **容器子节点不写 path/lines** → 只写 `members`
- **行号 0-indexed** → 第一行是 line 0
- **增量优先** → 已有项目用 `preserve_existing: true` patch
- **文件已存在时不覆盖** → 脚本智能合并 import + method
- **非代码文件也支持** → Dockerfile、Makefile、CI YAML、SQL、配置文件都会被索引
- **git-diff 模式** → 用 `--git-diff` 替代 `--diff` 可获得更精确的变更内容（AI 能看到实际的 + 行/- 行），工程项目建议使用此模式
- **首次使用** → 先读 `references/incremental-workflows.md`
