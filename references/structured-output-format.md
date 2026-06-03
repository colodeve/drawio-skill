# Structured Output Format

LLM 输出紧凑的 YAML。脚本自动转 XML + 计算布局。本文档定义完整 YAML schema。

如果只需要快速参考，先读 `SKILL.md` 的 YAML 速查部分。这里包含所有字段的完整定义。

---

## 文件级字段

```yaml
action: create | patch | scaffold
existing: diagram.drawio   # 基线文件路径（patch 模式必需）
output: diagram.drawio     # 输出路径（可选，默认覆盖 existing）
```

- `create`：从零创建图表
- `patch`：基于现有图表增量更新
- `scaffold`：基于图表生成代码骨架

---

## 节点（nodes / add_nodes）

```yaml
nodes:                       # create 模式用
  - id: unique_id            # 必填，全局唯一 [a-zA-Z0-9_] — 仅英文
    label: "显示文本"         # 必填，可多语言
    type: service            # 控制颜色和形状 — 仅英文
    group: services          # 所属泳道/分组名 — 仅英文
    path: ../src/app.ts      # 代码路径 — 仅英文
    lines: [0, 119]          # [start, end] 0-indexed — 仅数字
    container: true          # true = 泳道容器 — 仅布尔值
    members:                 # 容器内子文本行 — 可多语言
      - "方法签名或描述"
    scale: 1.0               # 语义权重 — 仅数字
    description: "..."       # 描述 — 可多语言
```

### 节点类型（type）

| type | 填充 | 描边 | 形状 | 适用 |
|------|------|------|------|------|
| `entry`, `config` | #fff7e6 | #fa8c16 | rounded | main、配置、manifest |
| `service`, `logic` | #e6f7ff | #1890ff | rounded | 业务逻辑、服务类 |
| `data`, `model`, `database` | #f6ffed | #52c41a | cylinder | 数据模型、SQL、GraphQL |
| `external`, `api` | #fff1f0 | #f5222d | hexagon | 外部 API、第三方服务 |
| `controller`, `ui` | #f9f0ff | #722ed1 | rounded | 控制器、UI 组件 |
| `infrastructure`, `middleware` | #f0f5ff | #2f54eb | rounded | Dockerfile、Makefile、CI YAML |
| `gateway` | #ffe6cc | #d79b00 | rounded | 网关 |
| `queue` | #fff2cc | #d6b656 | rounded | 消息队列 |
| `decision` | #fff7e6 | #fa8c16 | rhombus | 判断节点 |

不用手写 style，只写 `type`，脚本自动映射。

> **非代码文件类型推断：** Dockerfile → infrastructure，Makefile → infrastructure，
> `.github/workflows/*.yml` → infrastructure，`.json`/`.toml`/`.cfg` → config，
> `.sql`/`.graphql` → data。

### 容器节点（container）

```yaml
- id: scheduler
  label: scheduler()
  type: controller
  container: true
  members:
    - "Round-robin: iterates proc[]"
    - "Calls swtch() to context switch"
```

渲染效果：
- 节点以 `swimlane` + `childLayout=stackLayout` 渲染
- 标题栏（label）**可双击跳转**到源代码
- 子文本行（members）自动堆叠排版
- `autosizeText=1` 保证文字不溢出节点
- 子文本行**不写 path/lines**，纯展示

### 语义权重（scale）

```yaml
- id: core_svc
  label: CoreService
  scale: 1.5       # 比普通节点大 50%
- id: helper
  label: HelperUtil
  scale: 0.7       # 更紧凑
```

scale 影响节点宽高：`width = base_width * scale`, `height = base_height * scale`。适合将重要模块视觉上突出。

### id 规范

- 只能包含 `[a-zA-Z0-9_]`
- 全局唯一，即使在不同 group 中
- 推荐：`groupName_elementName`，如 `svc_user`, `ctrl_api`

### label 规范

- 简洁，1-3 个词
- 函数/方法加 `()`：`handleRequest()`
- 容器节点：标题即 label，子文本行在 members 中

---

## 注释框（notes）

```yaml
notes:                       # 装饰性注释框
  - text: "说明文字\n多行支持"
    group: proc_mgmt         # 放在哪个 group 底部 — 仅英文
    width: 200
    height: 80
```

渲染效果：
- `shape=note` + `autosizeText=1`（文字自动缩放填充）
- 黄色便签风格（fillColor=#FFF9B2）
- **不写 x/y 坐标**：脚本自动放置在 group 底部
- 脚本自动扩展 group 高度以容纳注释框

---

## 边（edges / add_edges）

```yaml
edges:                       # create 模式用
  - from: source_id          # 必填，源节点 id — 仅英文
    to: target_id            # 必填，目标节点 id — 仅英文
    label: imports           # 边上文本 — 可多语言
    path: ../src/a.ts        # 代码路径 — 仅英文
    lines: [5, 5]            # 代码行号 — 仅数字
    style: dashed            # dashed | solid — 仅英文
```

### 边标签语义

| label | 含义 |
|-------|------|
| `imports` / `uses` | import/require 关系 |
| `calls` | 函数调用 |
| `extends` | 继承 |
| `contains` / `has-a` | 组合/聚合 |
| `returns` / `responds` | 返回/响应 |
| `publishes` / `consumes` | 消息发布/消费 |
| `reads` / `writes` | 数据读写 |

### style

- `solid`（默认）— 强依赖、同步调用
- `dashed` — 弱依赖、异步调用、可选依赖

### 边路由自动处理

- 障碍物感知（20px clearance）
- 自动选择 L 形或 Z 形正交折线
- 同一坐标的边自动偏移避免重叠
- 源/目标所属的 group 不作为障碍物

---

## 增量变更（patch 模式专用）

```yaml
action: patch
existing: diagram.drawio

add_nodes:
  - id: new_node
    label: "New Service"
    type: service
    container: true
    members:
      - "process() → Result"
    group: services
    path: ../src/services/new.ts
    lines: [0, 49]

delete_nodes:
  - id: old_node_id

update_nodes:
  - id: existing_node
    label: "New Name"         # 修改标签
    lines: [0, 199]           # 更新行号
    type: service             # 修改类型
    path: ../src/services/x.ts # 修改路径
    group: new_group          # 移动分组

add_edges:
  - from: a
    to: new_node
    label: calls

delete_edges:
  - from: a
    to: old_node_id

# 分组变更
add_groups:
  - name: new_layer
    label: "New Layer"
    type: infrastructure

delete_groups:
  - name: old_layer

update_groups:
  - name: services
    label: "Business Services"
```

**增量更新原则：**
- **只写变更部分**，未变更的不出现
- `preserve_existing: true` 保持未变节点坐标
- `add_nodes` 的 ID 自动去重（重复则追加 `_1` 后缀）
- `delete_nodes` 级联删除关联边

---

## 代码骨架（scaffold 模式专用）

```yaml
action: scaffold
existing_code: src/

create_files:
  - path: src/services/new.ts
    language: typescript
    template: class | interface | function | enum
    class_name: NewService
    extends: BaseService
    implements: [IService]
    imports:
      - from: "../types"
        names: [TypeA, TypeB]
    methods:
      - name: process
        params:
          - name: data
            type: DataDTO
        return_type: Result

modify_files:
  - path: src/gateway.ts
    operations:
      - type: import
        content: "import { NewService } from './services/new';"
      - type: inject_method
        target_class: Gateway
        method: handleNew

delete_files:
  - path: src/services/old.ts

rename_files:
  - from: src/services/old.ts
    to: src/services/legacy.ts
```

### template 类型

| template | 适用 |
|----------|------|
| `class` | 类骨架 |
| `interface` | 接口定义 |
| `function` | 函数/工具文件 |
| `enum` | 枚举 |
| `type` | TypeScript type alias |
| `module` | 模块/namespace |

### 智能合并行为

脚本 `apply_scaffold` 的执行逻辑：

| 场景 | 行为 |
|------|------|
| `create_files` + 文件不存在 | 创建占位文件（import + class + method stub） |
| `create_files` + 文件已存在 | 注入 import（去重） + 追加 method stub（用 `find_block` 定位） |
| `modify_files` | 按 operation 类型执行（import / inject_method / inject_property / append） |
| `delete_files` | 移动到 `.drawio-backups/`（非永久删除） |
| 所有修改 | 自动生成 `.bak` 备份 |

---

## 布局配置（layout）

```yaml
layout:
  algorithm: layered        # layered | grid | hub | flow | tree | preserve
  direction: top-to-bottom  # left-to-right | bottom-to-top | right-to-left
  preserve_existing: true   # patch 模式下保留未变更节点位置
  spacing:                  # 间距覆写（可选）
    horizontal: 60
    vertical: 80
  route_spacing: 16         # 边偏移间距
  page:
    width: 1600
    height: 1200
```

### algorithm 详解

| 算法 | 适用场景 | 说明 |
|------|---------|------|
| `layered` | 架构图（默认） | 分层排列，top-to-bottom |
| `grid` | 模块地图 | 网格排列 |
| `hub` | 微服务 | 中心节点 + 周边节点 |
| `flow` | 数据流 | 等同于 layered |
| `tree` | 类层次 | 递归树形排列 |
| `preserve` | 增量更新 | 保持已有坐标，只排新增节点 |

### direction

- `top-to-bottom` — 数据流向下（默认）
- `left-to-right` — 流程向右
- `bottom-to-top` — 逆向分层
- `right-to-left` — 逆向流程

---

## 分组（groups）

在 `create` 模式下，group 通过 `nodes[].group` 隐式声明。如需显式定义 group 属性：

```yaml
groups:
  - name: services
    label: "Services Layer"
    type: service              # group 本身的颜色类型
    path: src/services/        # 目录路径
  - name: data
    label: "Data Layer"
    type: data
```

Group 是泳道（swimlane），自动包含同名的节点。脚本自动：
1. 计算 group 大小（基于节点实际高度）
2. 排列节点（按行/列，自动居中）
3. 扩展 group 高度以容纳注释框

---

## 完整示例：create

```yaml
action: create
output: docs/arch.drawio

groups:
  - name: api
    label: API Layer
    type: gateway
  - name: services
    label: Service Layer
    type: service
  - name: data
    label: Data Layer
    type: data

nodes:
  - id: gateway
    label: APIGateway
    type: gateway
    container: true
    group: api
    path: ../src/gateway.ts
    lines: [0, 79]
    members:
      - "handles HTTP requests"
      - "routes to services"

  - id: user_svc
    label: UserService
    type: service
    group: services
    path: ../src/services/user.ts
    lines: [0, 149]

  - id: user_db
    label: UserDB
    type: database
    group: data
    path: ../src/models/user.ts
    lines: [0, 59]

edges:
  - from: gateway
    to: user_svc
    label: calls
    path: ../src/gateway.ts
    lines: [20, 20]
  - from: user_svc
    to: user_db
    label: queries
    path: ../src/services/user.ts
    lines: [80, 80]

notes:
  - text: "API Gateway 是系统的唯一入口"
    group: api
    width: 200
    height: 80

layout:
  algorithm: layered
  direction: top-to-bottom
```

---

## YAML 书写规则（降低 Token）

1. **省略默认值**：不写 `style`, `width`, `height`, `x`, `y`
2. **紧凑数组**：`lines: [0, 119]` 而非 `start_line: 0\n  end_line: 119`
3. **一行一条边**：`{from: a, to: b, label: calls}`
4. **复用 group**：同 group 的节点只声明一次 group 名
5. **不声明未变更**：patch 模式下只写变化的部分
6. **用 scale 替代手写宽高**
7. **用 members 替代多行 label**
