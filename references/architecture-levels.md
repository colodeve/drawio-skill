# Architecture Diagram Levels (L1-L4)

**核心原则**：脚本提供素材，AI 做设计。L2/L3 的节点、边、描述全部由 AI 从扫描报告分析得出。

---

## L1 — System Context

**范围**：系统边界、外部依赖、硬件、运行时环境。

**生成**：
```bash
python3 scripts/incremental_reader.py --scan --level L1 --generate --output diagrams/context.drawio
```
脚本自动检测系统头文件、Docker FROM 等外部依赖生成节点 + 项目中心节点。

**AI 补充**：
- 修改节点标签为更具描述性的名称
- 添加项目角色描述（如"RISC-V 教学操作系统内核"）
- 添加用户/外部系统角色（如"QEMU 模拟器"）
- `type: external` 用于外部节点，`type: entry` 用于项目节点

**约定**：
- 文件名: `{project}-context.drawio`
- 外部节点不设 `path`
- 边用 `dashed` 表示运行时依赖

---

## L2 — Module Architecture

**范围**：项目内部的模块分组与依赖关系。这是**最重要**的图，**完全由 AI 设计**。

### AI 工作流

**输入**：扫描报告中的 `files`、`import_relations`、`directories`

**设计步骤**：

1. **决定节点** — 扫描报告列出 68 个文件，但 L2 图不需要全部。AI 判断：
   - 哪些文件合并为一个模块节点（如 `proc.c` + `proc.h` → "进程管理"）
   - 哪些文件分解为多个节点（如 `fs.c` 中的 inode 管理和块分配可能拆开）
   - 哪些辅助文件不画入图（如 `types.h`、`param.h` 等工具头文件）

2. **写描述** — 每个节点前几行是 AI 写的简短中文/英文说明：
   ```yaml
   - id: process_mgmt
     label: 进程管理
     description: "进程创建、调度、销毁的核心模块\n"
                  "关键接口: fork(), exit(), wait(), scheduler()"
     type: controller
     group: core
     path: kernel/proc.c
     lines: [0, 691]
   ```

3. **画边** — **不用 import**，用精炼的描述性动词：
   - ✅ `调度`、`切换地址空间`、`读写 inode`、`分配内存`
   - ❌ `imports`、`depends on`、`调用`

4. **分组** — 泳道根据模块职责划分，不一定按目录：
   - xv6 示例：`core`（核心）、`fs`（文件系统）、`device`（设备驱动）、`user`（用户程序）

5. **增量更新** — 当文件变化时，AI 读新的扫描报告，判断是否需要：
   - 添加新节点
   - 删除已移除的节点
   - 更新节点行号
   - 修改边

**约定**：
- 文件名: `{project}-arch.drawio`，另存 `.yaml` 源文件
- 节点 ID 建议使用带前缀的语义名（`proc_mgmt`、`fs_layer`）
- `description` 字段 AI 必填

---

## L3 — Component Detail

**范围**：关键子系统的内部逻辑流、状态机、调用链。**完全由 AI 设计**。

### AI 工作流

**输入**：L2 图的节点设计（哪些模块值得深入）

**选择标准** — 哪些模块需要 L3 图：
- 逻辑复杂度高（多状态、多条件分支）
- 有明确的内部流程（如进程生命周期、系统调用路径）
- 涉及多个子组件协作（如文件系统栈）

**设计要点**：

1. **内部逻辑流** — 用节点表示步骤，边表示流转：
   ```yaml
   nodes:
     - id: fork_entry
       label: fork() 入口
       type: entry
       group: lifecycle
     - id: alloc_proc
       label: 分配进程控制块
       type: service
       group: lifecycle
     - id: copy_mem
       label: 复制地址空间
       description: "遍历用户页表，逐页复制\n包含 COW 优化判断"
       type: service
       group: lifecycle
   edges:
     - from: fork_entry
       to: alloc_proc
       label: 检查参数
     - from: alloc_proc
       to: copy_mem
       label: 分配成功
   ```

2. **控制流/分支** — 用 `type: decision`（菱形）表示条件判断：
   ```yaml
   - id: check_state
     label: "进程状态 == RUNNABLE?"
     type: decision
     group: scheduler
   ```

3. **notes 注释** — 大量使用，解释设计决策、关键算法、约束条件：
   ```yaml
   notes:
     - text: "xv6 调度策略：轮转法\n每次时钟中断触发 yield()\n就绪队列无优先级"
       group: scheduler
       width: 300
       height: 80
   ```

4. **代码引用** — 成员 `members` 可包含关键代码行或伪代码：
   ```yaml
   - id: scheduler
     label: scheduler()
     container: true
     members:
       - "for(;;)  // 无限循环"
       - "  acquire(&p.lock)"
       - "  if(p.state == RUNNABLE)"
       - "    swtch(&c.context, &p.context)"
   ```

**布局建议**：
- 流程类用 `flow` 或 `layered` + `left-to-right`
- 状态机用 `hub`（中心 + 周边状态）
- 引用 L2 节点的 ID 前缀（如 `l3_fork`、`l3_syscall`）

---

## L4 — Data Structures

**范围**：核心 struct/class/interface 的定义及其关系。类似 ER 图。

**生成**：
```bash
python3 scripts/incremental_reader.py --scan --level L4 --generate --output diagrams/data-structs.drawio
```
脚本自动提取所有 `.c/.h/.py/.java` 等文件中的 struct/class 定义及字段。

**AI 调整**：
1. **删减** — 扫描报告列出所有 struct，AI 只选核心的几个画入图（通常 2~10 张）
2. **合并** — 相关的 struct 合并到一个容器节点（如 `proc` + `context` + `trapframe` 合并为"进程相关结构"）
3. **加关系边** — 字段中的指针/引用转化为边：
   - `struct proc` 中的 `lock: spinlock` → `proc` → `spinlock`（边标签：持有锁）
   - `struct proc` 中的 `ofile[16]: file*` → `proc` → `file`（边标签：打开文件）
   - 类继承关系 → `extends`

**约定**：
- 文件名: `data-structs.drawio`
- struct 节点用 `type: data`
- 关系边用 `solid`（组合）或 `dashed`（引用）
- 关系边标签用动词或介词

---

## 文件组织

```
project/
├── diagrams/
│   ├── xv6-context.drawio       # L1 — 自动生成 + AI 补充
│   ├── xv6-arch.drawio          # L2 — AI 设计
│   ├── xv6-arch.yaml            # L2 源 YAML（AI 写的）
│   ├── proc-lifecycle.drawio    # L3 — AI 设计
│   ├── fs-stack.drawio          # L3
│   ├── syscall-flow.drawio      # L3
│   ├── data-structs.drawio      # L4 — 自动生成 + AI 调整
│   ├── core/
│   └── fs/
└── report.yaml                  # 扫描报告（AI 参考，不提交）
```

## 增量更新原则

| 层级 | 触发条件 | 操作 |
|------|---------|------|
| L1 | 新外部依赖出现 | 重新 `--level L1 --generate` |
| L2 | 代码文件新增/删除/重构 | 重新扫描 → AI 读报告 → 手动修改 YAML |
| L3 | 关键模块代码大幅变化 | AI 重审并更新对应子图 |
| L4 | struct/class 字段变化 | 重新 `--level L4 --generate`，AI 还原关系边 |

所有层级共用一套节点 ID 命名约定，方便跨图引用：
- L2: `模块_功能`（如 `fs_vfs`）
- L3: `l3_模块_流程`（如 `l3_fs_write`）
- L4: `l4_struct_名称`（如 `l4_struct_proc`）
