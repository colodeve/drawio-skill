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

## 四层架构图（L1-L4）

| 层级 | 名称 | 生成方式 | 增量更新 |
|------|------|---------|---------|
| **L1** | 系统上下文 | `--level L1 --generate` 自动生成 + AI 补充 | 扫描新外部依赖 |
| **L2** | 模块架构 | **AI 从扫描报告设计**，手动写 YAML | 扫描文件变化，AI 调整图 |
| **L3** | 组件细节 | **AI 从扫描报告设计**，手动写 YAML | 代码变化后 AI 重审 |
| **L4** | 数据结构 | `--level L4 --generate` 自动生成 + AI 改关系边 | struct 变化后重新生成 |

---

## 工作流

### 第一步：获取扫描报告

```bash
# 完整报告（AI 读）
python3 scripts/incremental_reader.py --project-root . --scan --output report.yaml
```

报告包含：
- `files` — 源文件列表（路径/类型/行数/是否有 struct），**AI 判断哪些文件需要画成 L2 节点**
- `import_relations` — 原始 import 依赖（**AI 决定哪些有意义**，不是全部画边）
- `directories` — 目录结构
- `struct_data` — struct/class 字段定义（L4 参考）
- `l1_externals` — 系统外部依赖

### 第二步：AI 设计各层图

**L2（模块架构）** — AI 根据报告手动写 YAML：
- 节点**不是**1:1对应文件。一个文件可能产生0/1/多个节点，多个文件可能合并为一个节点
- 文件列表只作为参考，AI 根据代码分析决定模块边界
- **边由 AI 设计**，用精炼标签描述关系（如"调度"、"读写"、"调用"），不用 import
- 每个节点前几行是 AI 写的简短描述
- 参见 `references/architecture-levels.md` 详细指导

**L3（组件细节）** — AI 为关键模块单独写 YAML：
- 内部逻辑流、状态机、调用链（if/while/条件分支）
- 大量使用 `notes` 作为设计注释
- 节点内容更详细，包含代码片段引用
- 引用 L2 节点 ID 保持跨图一致性

**L4（数据结构）** — 脚本自动生成 + AI 调整：
```bash
# 自动生成 struct/class 节点
python3 scripts/incremental_reader.py --scan --level L4 --generate --output diagrams/structs.drawio
```
- AI 在 YAML 上增删节点，添加关系边（类似 ER 图）

**L1（系统上下文）** — 脚本自动生成 + AI 补充：
```bash
python3 scripts/incremental_reader.py --scan --level L1 --generate --output diagrams/context.drawio
```

---

## YAML 输出格式（AI 写）

```yaml
nodes:
  - id: scheduler
    label: 进程调度器
    description: "管理 xv6 所有进程状态。\n核心函数: scheduler(), yield(), sleep(), wakeup()"  # AI 写
    type: controller
    group: proc_mgmt
    path: kernel/proc.c
    lines: [424, 691]
    container: true
    members:
      - "scheduler(): 轮转调度"
      - "yield(): 主动让出 CPU"
      - "sleep(): 等待事件"
      - "wakeup(): 唤醒进程"

  - id: allocator
    label: 物理内存分配器
    description: "基于空闲链表的页分配器\n每个 CPU 核心独立空闲链表减少锁竞争"  # AI 写
    type: service
    group: core
    path: kernel/kalloc.c
    lines: [0, 81]

notes:
  - text: "xv6 调度策略：轮转法\n每次时钟中断触发 yield\n就绪队列是 proc 数组的线性扫描"
    group: proc_mgmt
    width: 280
    height: 80

edges:           # AI 设计边，用精炼描述性标签
  - from: scheduler
    to: allocator
    label: 分配进程栈
    style: solid
  - from: scheduler
    to: vm
    label: 切换地址空间
    style: solid

layout:
  algorithm: layered
  direction: top-to-bottom
  preserve_existing: true
```

---

## 路径计算规则

YAML 中的 `path` 写**相对于 drawio 文件所在目录**的路径。脚本写入 XML 时会自动加一层 `../` 补偿 vscode-drawio 的路径解析行为。

| drawio 位置 | 代码位置 | YAML path |
|---|---|---|
| `根目录/arch.drawio` | `src/app.ts` | `src/app.ts` |
| `diagrams/arch.drawio` | `src/app.ts` | `../src/app.ts` |

---

## 多语言支持

节点上的显示文本可以跟随用户使用的语言。标识性字段保持英文/数字。

### 可本地化
`nodes[].label`, `members`, `description`, `notes[].text`, `groups[].label`, `edges[].label`

### 保持英文
`id`, `path`, `lines`, `type`, `container`, `scale`, `from`, `to`, `style`, `layout.*`, `action`

---

## 类型颜色映射

| type | 颜色 | 形状 | 适用场景 |
|---|---|---|---|
| `entry`, `config` | 橙 | rounded | 入口、配置 |
| `service`, `logic` | 蓝 | rounded | 业务逻辑 |
| `data`, `model`, `database` | 绿 | cylinder | 数据模型 |
| `external`, `api` | 红 | hexagon | 外部依赖 |
| `controller`, `ui` | 紫 | rounded | 控制器 |
| `infrastructure`, `middleware` | 靛 | rounded | 基础设施 |
| `gateway` | 金 | rounded | 网关 |
| `queue` | 黄 | rounded | 消息队列 |
| `decision` | 橙 | rhombus | 判断节点 |

只写 `type`，脚本自动映射颜色和形状。

---

## 脚本工具

| 脚本 | 用途 |
|---|---|
| `incremental_reader.py` | 扫描代码，输出报告(`.yaml`)。L4/L1 可用 `--generate` 自动生成 |
| `incremental_writer.py` | 从图生成/更新代码骨架（智能合并） |
| `layout_generator.py` | YAML → drawio XML（布局+边路由+容器节点+notes） |
| `analyzer.py` | 代码块查找、import 提取、struct 字段提取 |
| `import_graph.py` | import 依赖图分析 |
| `git_diff_reader.py` | git diff 封装 |
| `index_generator.py` | 刷新 `.vscode/drawio-code-links.json` |
| `export_diagram.py` | 导出 PNG/SVG/PDF |
| `layout_analyzer.py` | 布局验证 |
| `code_sync.py` | 同步图中的行号 |

---

## 关键提醒

- **不要手写 XML** → 永远输出 YAML
- **L2/L3 是 AI 设计** → 扫描报告只是素材，节点/边/描述由 AI 决定
- **L4 自动生成 struct/class 节点** → AI 在 YAML 上加关系边、删多余节点
- **路径规则** → YAML 填相对 drawio **目录**的路径，脚本自动补偿
- **容器子节点不写 path/lines** → 只写 `members`，同时设置 `container: true`
- **行号 0-indexed** → 第一行是 line 0
- **文件已存在时不覆盖** → 脚本智能合并 import + method
- **非代码文件也支持** → Dockerfile、Makefile、CI YAML、SQL、配置文件都会被索引
- **`--scan` 自动选择** → git 项目走 git-diff（O(变更数)），非 git 走文件哈希缓存
- **首次使用** → 先写 `references/architecture-levels.md`
