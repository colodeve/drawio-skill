# Draw.io Architect

一个增量式架构图生成与管理工具。通过结构化 YAML 驱动，Python 脚本自动计算布局、边路由与坐标，**无需手写 XML**。

---

## 多语言支持

**支持**。节点显示文本（`label`、`members`、`notes.text`、`group label`、`edges[].label`）可根据用户语言自动翻译输出。

标识性字段（`id`、`path`、`lines`、`type` 等）保持英文以确保稳定性。

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **增量读取** | 扫描代码变更（`git ls-files` + SHA-256 指纹），自动更新架构图 |
| **增量写入** | 从图表变更智能生成/更新代码骨架（追加 import/method，不覆盖） |
| **直接生成** | YAML → drawio XML，自动布局、避障边路由、容器节点 |
| **代码分析** | 函数级指纹，支持 15+ 编程语言 |
| **依赖图** | 自动分析 import 依赖关系 |
| **VS Code 联动** | 每个元素绑定 `hedietLinkedDataV1`，双击跳转源代码 |
| **导出** | PNG / SVG / PDF |
| **样式预设** | 按类型自动映射颜色与形状 |
| **非代码文件** | 支持 Dockerfile、Makefile、CI YAML、SQL、配置文件 |

---

## 快速开始

```bash
# 增量读取：代码变了，图跟着变
python3 scripts/incremental_reader.py --input src/ --output arch.drawio

# 直接生成：YAML 画图
python3 scripts/layout_generator.py --input diagram.yaml --output arch.drawio

# 导出
python3 scripts/export_diagram.py --input arch.drawio --format png
```

---

## 项目结构

```
├── SKILL.md                          # Skill 定义与使用指南
├── references/                       # 详细文档
│   ├── incremental-workflows.md      # 增量读写工作流
│   ├── structured-output-format.md   # YAML 格式规范
│   ├── layout-system.md              # 布局算法
│   ├── style-presets.md              # 样式预设
│   ├── export-commands.md            # 导出命令
│   └── tool-reference.md             # 脚本工具参考
└── scripts/                          # 核心脚本
    ├── incremental_reader.py
    ├── incremental_writer.py
    ├── layout_generator.py
    ├── analyzer.py
    ├── import_graph.py
    ├── export_diagram.py
    └── utils/
```

---

## 要求

- Python 3.8+
- 可选：draw.io CLI（用于 PNG 导出）

---

## 许可

MIT
