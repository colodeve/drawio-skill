# Layout System

This document defines the positioning rules used by `layout_generator.py` for
draw.io diagrams.

---

## Core Constants

| Constant | Code Value | Default | Description |
|----------|-----------|---------|-------------|
| `GRID_SIZE` | `GRID_SIZE` | 10 | Base grid unit (px) |
| `ELEM_WIDTH` | `DEFAULT_ELEM_WIDTH` | 140 | Default element width |
| `ELEM_HEIGHT` | `DEFAULT_ELEM_HEIGHT` | 60 | Default element height |
| `ELEM_GAP_H` | `DEFAULT_ELEM_GAP_H` | 60 | Horizontal gap between nodes in a row |
| `ELEM_GAP_V` | `DEFAULT_ELEM_GAP_V` | 90 | Vertical gap between rows |
| `GROUP_PADDING` | `DEFAULT_GROUP_PADDING` | 30 | Internal padding within a group (left/right) |
| `GROUP_TOP_PAD` | `DEFAULT_GROUP_TOP_PAD` | 50 | Top padding inside group (accounts for header). Note: draw.io `startSize=30` controls the swimlane header height. `GROUP_TOP_PAD=50` includes the 30px header + 20px extra padding before the first child node. |

> Values shown are defaults. All are overridable via YAML `layout.spacing.*`.

> **关于 GROUP_TOP_PAD 与 startSize 的关系**：draw.io 的 `startSize=30` 控制 swimlane 标题栏高度。
> 布局引擎的 `GROUP_TOP_PAD=50` = `startSize(30) + 20px 额外间距`，因此子节点从 y=50 开始排列而非 y=30。
> 这个 20px 额外间距是固定值，不由配置控制。

---

## Layout Algorithms

### `layered` — 分层排列（默认）

Groups arranged in rows, nodes arranged within each group in row-major order.

**Direction support:** `top-to-bottom` / `bottom-to-top` / `left-to-right` / `right-to-left`

**Use cases:** Architecture layers, n-tier systems, class hierarchies.

#### Group Position

```
cols = ceil(sqrt(NUM_GROUPS))
row = floor(group_index / cols)
x = CANVAS_MARGIN + col * (group_width + GROUP_GAP_H)
y = CANVAS_MARGIN + row * (group_height + GROUP_GAP_V)
```

#### Group Size

Group dimensions are computed from actual node sizes (not fixed defaults):

```
num_cols = min(3, len(children))
num_rows = ceil(len(children) / num_cols)

# Group width: max node width per column + padding
content_width = num_cols * max_node_width + (num_cols-1) * ELEM_GAP_H + 2 * GROUP_PADDING

# Group height: tallest node per row, stacked
total_height = GROUP_TOP_PAD
for each row:
    total_height += max(node_heights_in_row)
total_height += (num_rows-1) * ELEM_GAP_V + 20

group.width = max(300, content_width)
group.height = max(150, total_height)
```

**Important:** Group height is dynamic. Container nodes with many `members` are taller than regular nodes, and the group expands to fit them. Notes placed at group bottom also expand group height.

#### Node Position Within Group

```
# Build per-row node lists
rows = [list of nodes per row]

current_y = group.y + GROUP_TOP_PAD
for each row:
    row_height = max(_node_height(n) for n in row_nodes)   # actual max height
    for each node in row:
        node.x = group.x + padding + col * (node_width + ELEM_GAP_H)
        node.y = current_y
        node.width = _node_width(node)
        node.height = _node_height(node)
    current_y += row_height + ELEM_GAP_V
```

Each row's Y is determined by the **tallest node in the previous row**, not a fixed constant.

---

### `grid` — 网格排列

Nodes arranged in a fixed grid (no groups).

```
cols = max(2, sqrt(N))
for i, node in enumerate(nodes):
    col = i % cols
    row = i // cols
    node.x = CANVAS_MARGIN + col * (ELEM_WIDTH + spacing_h)
    node.y = CANVAS_MARGIN + row * (ELEM_HEIGHT + spacing_v)
```

**Use cases:** Module maps, monorepo overviews.

---

### `hub` — 中心辐射

Central node (most connected) surrounded by satellites in a circle.

```
center at (page_width/2, page_height/3)
satellites placed in circle with radius = min(400, n * 60)
```

**Use cases:** Microservices with gateway, event-driven systems.

---

### `tree` — 树形排列

Builds parent-child tree from edges, recursively positions subtrees.

```
level_height = node_height + ELEM_GAP_V
parent centered over children
```

**Use cases:** Class hierarchies, directory structures.

---

### `preserve` — 保留坐标

Keeps existing node coordinates. Only positions new nodes (those at origin `x≈0, y≈0`) near their connected neighbors.

**Use cases:** Incremental patch updates.

---

## Node Size Calculation

```python
def _node_height(node):
    if node.container and node.members:
        base = 30 + len(node.members) * 22 + 10   # header + member lines + padding
    else:
        base = DEFAULT_ELEM_HEIGHT                  # 60
    return base * node.scale

def _node_width(node):
    if node.container and node.members:
        base = max(DEFAULT_ELEM_WIDTH, 160)          # at least 160 for text
    else:
        base = DEFAULT_ELEM_WIDTH                    # 140
    return base * node.scale
```

Container nodes with `members` are taller than regular nodes. The `scale` field
multiplies the base size — `scale: 1.5` = 50% larger.

---

## Notes Positioning

Notes (`notes:` in YAML) are placed at the bottom of their parent group
after all node positions are computed:

```
max_bottom = max(child.y + child.height for all children in group)
note.y = max_bottom + ELEM_GAP_V - group.y   # relative to group
note.x = GROUP_PADDING                        # relative to group
```

If the note extends past the group's current bottom, the group height is
expanded automatically to contain it.

---

## Edge Routing

### Obstacle Avoidance

Every edge route is checked against all nodes and groups (with 20px clearance).
Source and target nodes, and groups containing source/target, are excluded
from obstacle detection.

### Routing Strategy

```
1. Try L-shaped (1 bend) — current orientation (horizontal-first or vertical-first)
2. Try flipped L-shaped — other orientation
3. If both blocked: Z-shaped (2 bends) pushed to nearest clear gap
```

**All routes are orthogonal** (horizontal + vertical segments only).
A post-processing step (`_ensure_orthogonal_routes`) corrects any diagonal
segments introduced by segment offsetting.

### Clearance

Edge segments maintain `EDGE_CLEARANCE = 20px` from node and group boundaries.
This prevents edges from "touching" or "hugging" the borders of obstacles.

### Segment Offsetting

When multiple edges share the same coordinate (e.g., two horizontal segments
at the same Y), they are offset by `ROUTE_SPACING = 16px` to avoid overlap.
The offset alternates above and below the original coordinate.

---

## Canvas Sizing

If `layout.auto_size` is `true` (default), the canvas expands to fit all
nodes after layout:

```python
max_x = max(node.x + node.width for all nodes)
max_y = max(node.y + node.height for all nodes)
page_width = max(original, max_x + CANVAS_MARGIN)
page_height = max(original, max_y + CANVAS_MARGIN)
```

---

## Anti-Overlap Rules

1. **No overlapping groups** — group bounding boxes must never intersect
2. **No overlapping nodes** — `LayoutEngine._fix_overlaps()` pushes apart any
   nodes that overlap (up to 3 iterations)
3. **No nodes outside their group** — group height auto-expands for containers
   and notes
4. **Minimum gap enforcement** — `ELEM_GAP_H`, `ELEM_GAP_V` maintained
5. **Edge clearance** — 20px from all obstacles
