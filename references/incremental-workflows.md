# Incremental Workflows

本文档详细描述增量读取和增量写入两个工作流的完整步骤、决策点和错误处理。

> **需要详细了解每个脚本的参数和用法？** → 先读 `references/tool-reference.md`。

---

## 通用工具定位

| 脚本 | 在 workflow 中的角色 | 关键参数 |
|------|---------------------|---------|
| `incremental_reader.py` | 读取工作流核心 | `--diff` 检测变更 → YAML → `--patch` 应用 |
| `incremental_writer.py` | 写入工作流核心 | `--diff` 分析差异 → YAML → `--plan --apply` |
| `layout_generator.py` | 自动布局（被 reader 内部调用） | `--input` YAML → `--output` drawio |
| `code_sync.py` | 同步行号（两个 workflow 都需要） | `--update-lines --sync` 写入，不加 `--sync` 为 dry-run |
| `index_generator.py` | 更新 VS Code 索引（自动调用） | `--workspace .` 或 `--drawio file.drawio` |
| `import_graph.py` | 分析 import → 建议边（`--diff` 自动调用） | 不直接调用 |
| `analyzer.py` | 代码块查找、import 提取、指纹计算 | 被其他脚本调用 |
| `export_diagram.py` | 导出 PNG/SVG（最终交付） | `--format png --scale 2` |

---

## 工作流 1：增量读取（Incremental Read）

从代码变更自动生成/更新架构图。核心原则：**最小变更、最大复用**。

### Step 1: 检查现有图表

**检查路径优先级：**
1. 用户指定的 `.drawio` 文件路径
2. 项目根目录下的 `diagram.drawio`
3. `docs/` 下的 `*.drawio`
4. 当前目录下的 `*.drawio`

**无现有图表 → create 模式（直接生成）**
- 扫描项目结构
- 输出完整的 `action: create` YAML
- `layout_generator.py` 全量生成

**有现有图表 → patch 模式**
- 读取现有图表作为基线
- 进入 Step 2

// ... existing code ...

### Step 2: 分析代码变更

```bash
python3 scripts/incremental_reader.py --project-root . --existing diagram.drawio --diff
```

**扫描策略：** 自动使用 `git ls-files`（快、遵守 `.gitignore`），非 git 项目回退 `os.walk`。

**指纹检测（SHA-256 内容哈希 + 函数级指纹）：**

| 变更类型 | 含义 | 你的处理 |
|----------|------|---------|
| `new` | 新增文件 | 在 `add_nodes` 中添加节点 |
| `deleted` | 文件被删除 | 在 `delete_nodes` 中删除节点 |
| `structural` | 代码逻辑变了 | 更新 `lines`（行号），或调整节点 |
| `cosmetic` | 只改了注释/格式 | 跳过，不影响图表 |
| `none` | 未变 | 跳过 |

> 脚本使用**函数级指纹**（每函数的独立 SHA-256）来精确定位变更，
> 比文件级哈希更精确——能区分"哪个函数变了"而非"哪个文件变了"。

**输出报告包含：**
- `new_files` — 新增文件及其路径、类型、行数
- `deleted_files` — 被删除的文件路径
- `modified_files` — 结构性变化的文件（旧/新行数）
- `orphaned_nodes` — 因文件删除而悬空的节点
- `suggested_edges` — 脚本分析 import 图后自动建议的边
- `structural_changes` — 真正影响图结构的文件列表

### Step 3: 你输出 patch YAML

```yaml
action: patch
existing: diagram.drawio

add_nodes:
  - id: payment
    label: PaymentService
    type: service
    container: true
    group: services
    path: ../src/services/payment.ts
    lines: [0, 79]
    members:
      - "processPayment(amount) -> PaymentResult"
      - "refund(transactionId) -> bool"

delete_nodes:
  - id: old_auth

update_nodes:
  - id: user
    lines: [0, 149]

add_edges:
  - from: api
    to: payment
    label: routes

delete_edges:
  - from: api
    to: old_auth

layout:
  algorithm: layered
  direction: top-to-bottom
  preserve_existing: true
```

**关键决策点：**

| 场景 | 你的处理 |
|---|---|
| 新增文件 | `add_nodes` + `add_edges`（基于 import 分析） |
| 文件删除 | `delete_nodes` + `delete_edges`（级联删除关联边） |
| 行号偏移 | `update_nodes` 更新 `lines` |
| 文件重命名 | `update_nodes` 更新 `path` |
| 新增 import | `add_edges` |
| 删除 import | `delete_edges` |

**保留坐标原则：**
- 未变更节点保留原位置（`preserve_existing: true`）
- 新增节点自动插入到逻辑相邻位置
- 新增容器节点自动计算大小（含 members 高度）

### Step 4: 脚本生成并验证

```bash
python3 scripts/incremental_reader.py --patch patch.yaml --existing diagram.drawio --output diagram.drawio
```

脚本内部流程：
1. **加载基线**：读取现有 `.drawio`，提取所有节点/边/坐标
2. **应用 patch**：添加/删除/更新节点和边
3. **布局计算**（`layout_generator.py`）：
   - 未变更节点保留原坐标
   - 新增节点计算插入位置
   - 容器节点按 `members` 数量决定高度
   - 边路由避开障碍物（20px clearance）
4. **验证**：检测重叠、越界
5. **输出 XML**：生成 `.drawio` 文件
6. **自动更新索引**：刷新 `.vscode/drawio-code-links.json`

### Step 5: 导出预览

```bash
# 方式 A：有 draw.io CLI
python3 scripts/export_diagram.py --input diagram.drawio --format png --scale 2

# 方式 B：无 CLI，生成浏览器 URL
python3 scripts/export_diagram.py --input diagram.drawio --browser-fallback
```

### 错误处理

| 错误 | 处理 |
|---|---|
| patch 中引用不存在的节点 ID | 脚本报错，提示可用 ID 列表 |
| 新增节点 ID 重复 | 脚本自动追加 `_1`, `_2` 后缀 |
| 布局后仍有重叠（3 轮修复后） | 脚本扩大画布尺寸 |
| 节点路径不存在 | 标记为 "orphaned" |
| 边 source/target 缺失 | 删除孤立边 |

---

## 工作流 2：增量写入（Incremental Write）

从图表变更自动生成/更新代码。核心原则：**代码安全、不覆盖已有实现**。

### Step 1: 解析差异

```bash
python3 scripts/incremental_writer.py --drawio diagram.drawio --project-root . --diff
```

### Step 2: 你输出 scaffold YAML

```yaml
action: scaffold
existing_code: src/

create_files:
  - path: src/services/payment.ts
    language: typescript
    template: class
    class_name: PaymentService
    description: Handles payment processing
    imports:
      - from: "./types"
        names: [PaymentDTO]
    methods:
      - name: processPayment
        params:
          - name: amount
            type: number
        return_type: PaymentResult
```

### Step 3: 脚本智能合并

```bash
python3 scripts/incremental_writer.py --plan scaffold.yaml --apply
```

脚本行为：

| 场景 | 行为 |
|---|---|
| `create_files` + 文件不存在 | 创建占位文件（import + class + method stub） |
| `create_files` + 文件已存在 | **智能合并**：注入 import（去重）+ 追加 method stub |
| `modify_files` | 按 operation 类型执行（import / inject_method 等） |
| `delete_files` | 移动到 `.drawio-backups/`（非永久删除） |
| 所有修改 | 自动生成 `.bak` 备份 |

**代码安全原则：**
1. 不覆盖已有实现
2. 智能注入：在现有文件中插入 import 和方法，保留原文件内容
3. 生成备份

### Step 4: 同步行号

```bash
python3 scripts/code_sync.py --drawio diagram.drawio --project-root . --update-lines --sync
```

行号查找策略：
1. 读取节点的 `path` 对应文件
2. 用 `analyzer.py` 的 `find_block()` 查找节点 label 对应的类/函数定义
3. 更新 `hedietLinkedDataV1_start_line_x-num` / `hedietLinkedDataV1_end_line_x-num`
4. 如果找不到匹配（如 label 是 "contains"），记录错误但不修改

---

## 双向同步策略

**当代码变更时：**
1. 运行增量读取流程 → 更新图表行号、标记删除
2. 图表保持最新

**当图表变更时：**
1. 运行增量写入流程 → 更新代码文件
2. 再运行 `code_sync.py` 更新图表行号

**推荐工作流：**
- 开发者修改代码 → 提交前运行 `incremental_reader.py --diff` 更新图表
- 架构师修改图表 → 运行 `incremental_writer.py --diff --plan --apply` 生成代码骨架
