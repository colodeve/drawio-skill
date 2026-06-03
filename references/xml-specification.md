# XML Specification for hediet Linked Data

This document defines the exact XML format for creating draw.io elements that link
to source code via the hediet VS Code draw.io extension.

---

## Object Wrapper Pattern

Every code-linked element MUST use the `<object>` wrapper. The `<object>` element
carries the linking metadata, while the inner `<mxCell>` defines the visual appearance.

```xml
<object label="DISPLAY_NAME"
        hedietLinkedDataV1_path="RELATIVE_FILE_PATH"
        hedietLinkedDataV1_start_line_x-num="START_LINE"
        hedietLinkedDataV1_end_line_x-num="END_LINE"
        id="UNIQUE_ID">
    <mxCell style="STYLE_STRING" vertex="1" parent="PARENT_ID">
        <mxGeometry x="X_POS" y="Y_POS" width="WIDTH" height="HEIGHT" as="geometry"/>
    </mxCell>
</object>
```

---

## Attribute Reference

### `<object>` Attributes

| Attribute | Required | Description |
|-----------|----------|-------------|
| `label` | Yes | Display text shown on the diagram element. Keep concise. |
| `hedietLinkedDataV1_path` | Yes | Relative path from the drawio file to the source file (note: path is resolved relative to the drawio FILE, not its directory). Use forward slashes. |
| `hedietLinkedDataV1_start_line_x-num` | Yes | Starting line number (0-indexed, matches VS Code `Position.line`). Use `0` if not yet linked. |
| `hedietLinkedDataV1_end_line_x-num` | Yes | Ending line number (0-indexed, matches VS Code `Position.line`). Use `0` if not yet linked. |
| `hedietLinkedDataV1_symbol` | No | Hierarchical symbol path (e.g. `ClassName.methodName`). Alternative to line range. |
| `id` | Yes | Unique identifier within the diagram. |

### `<mxCell>` Attributes

| Attribute | Required | Description |
|-----------|----------|-------------|
| `style` | Yes | CSS-like style string defining visual appearance. |
| `vertex` | For nodes | Set to `"1"` for node elements. |
| `edge` | For edges | Set to `"1"` for edge elements. |
| `parent` | Yes | ID of the parent element. Use `"1"` for top-level, or a group ID. |

### `<mxGeometry>` Attributes — Nodes

| Attribute | Required | Description |
|-----------|----------|-------------|
| `x` | Yes | X position in pixels. |
| `y` | Yes | Y position in pixels. |
| `width` | For nodes | Width in pixels. |
| `height` | For nodes | Height in pixels. |
| `as` | Yes | Always set to `"geometry"`. |

For edges, `<mxGeometry>` uses `relative="1"` instead of x/y/width/height:
```xml
<mxGeometry relative="1" as="geometry"/>
```

---

## Complete Node Examples

### Rounded Rectangle (Service/Logic)

```xml
<object label="UserService"
        hedietLinkedDataV1_path="../src/services/UserService.ts"
        hedietLinkedDataV1_start_line_x-num="0"
        hedietLinkedDataV1_end_line_x-num="44"
        id="3">
    <mxCell style="rounded=1;whiteSpace=wrap;html=1;fillColor=#e6f7ff;strokeColor=#1890ff;fontSize=12;fontStyle=1" vertex="1" parent="1">
        <mxGeometry x="300" y="200" width="140" height="60" as="geometry"/>
    </mxCell>
</object>
```

### Container Node (swimlane + stackLayout)

```xml
<object label="scheduler()"
        hedietLinkedDataV1_path="../../kernel/proc.c"
        hedietLinkedDataV1_start_line_x-num="424"
        hedietLinkedDataV1_end_line_x-num="691"
        id="17">
    <mxCell style="swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;startSize=30;horizontalStack=0;resizeParent=1;resizeParentMax=0;resizeLast=0;collapsible=1;marginBottom=0;whiteSpace=wrap;html=1;autosizeText=1;fillColor=#f9f0ff;strokeColor=#722ed1" vertex="1" parent="3">
        <mxGeometry x="30" y="50" width="160" height="106" as="geometry"/>
    </mxCell>
</object>
<mxCell id="18"
        style="text;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;spacingLeft=4;spacingRight=4;autosizeText=1;fontSize=10;points=[[0,0.5],[1,0.5]];portConstraint=eastwest;rotatable=0;whiteSpace=wrap;html=1;"
        value="Round-robin: iterates proc[] for RUNNABLE"
        vertex="1" parent="17">
    <mxGeometry y="30" width="160" height="22" as="geometry"/>
</mxCell>
```

Container node key points:
- The `<object>` carries `hedietLinkedDataV1_*` attributes (for double-click jump)
- Child `<mxCell>` entries are **text-only** — no code linking, pure display
- Children use the container node's ID as their `parent`
- Container height is determined by member count: `30 (header) + n * 22 + 10`

### Note (comment box)

```xml
<mxCell id="98"
        style="shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;autosizeText=1;fontColor=#000000;darkOpacity=0.05;fillColor=#FFF9B2;strokeColor=none;fillStyle=solid;fontSize=14;direction=west;gradientDirection=north;gradientColor=#FFF2A1;shadow=1;size=20;pointerEvents=1;"
        value="Comment text here"
        vertex="1" parent="2">
    <mxGeometry x="30" y="290" width="200" height="100" as="geometry"/>
</mxCell>
```

Notes are generated from the `notes:` section in YAML. They are placed
automatically at the bottom of their parent group by `_position_notes()`.

### Cylinder (Database/Model)

```xml
<object label="UserModel"
        hedietLinkedDataV1_path="../../src/models/User.ts"
        hedietLinkedDataV1_start_line_x-num="0"
        hedietLinkedDataV1_end_line_x-num="29"
        id="5">
    <mxCell style="shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;fillColor=#f6ffed;strokeColor=#52c41a;fontSize=12" vertex="1" parent="1">
        <mxGeometry x="300" y="400" width="120" height="80" as="geometry"/>
    </mxCell>
</object>
```

### Hexagon (External API)

```xml
<object label="PaymentAPI"
        hedietLinkedDataV1_path="../../src/external/payment.ts"
        hedietLinkedDataV1_start_line_x-num="0"
        hedietLinkedDataV1_end_line_x-num="49"
        id="9">
    <mxCell style="shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;fillColor=#fff1f0;strokeColor=#f5222d;fontSize=12" vertex="1" parent="1">
        <mxGeometry x="550" y="200" width="130" height="60" as="geometry"/>
    </mxCell>
</object>
```

---

## Group (Swimlane) Pattern

```xml
<object label="User Module"
        id="10">
    <mxCell style="swimlane;startSize=30;whiteSpace=wrap;html=1;fillColor=#f0f5ff;strokeColor=#2f54eb;fontSize=14;fontStyle=1;swimlaneLine=1" vertex="1" parent="1">
        <mxGeometry x="50" y="50" width="400" height="300" as="geometry"/>
    </mxCell>
</object>

<object label="UserController"
        hedietLinkedDataV1_path="../../src/modules/user/controller.ts"
        hedietLinkedDataV1_start_line_x-num="0"
        hedietLinkedDataV1_end_line_x-num="39"
        id="11">
    <mxCell style="rounded=1;whiteSpace=wrap;html=1;fillColor=#f9f0ff;strokeColor=#722ed1;fontSize=11" vertex="1" parent="10">
        <mxGeometry x="30" y="50" width="120" height="50" as="geometry"/>
    </mxCell>
</object>
```

Key points about groups:
- The group's `<object>` label becomes the swimlane header text
- Child elements use the group's ID as their `parent` value
- Child element positions are **relative to the group**, not the canvas
- `startSize=30` reserves 30px for the header; child elements start at y >= 40

---

## Edge (Connection) Pattern

Edges connect two elements. They can carry linking data if the connection
represents a specific code relationship.

### Edge with Label

```xml
<object label="calls"
        hedietLinkedDataV1_path="../../src/controllers/UserController.ts"
        hedietLinkedDataV1_start_line_x-num="14"
        hedietLinkedDataV1_end_line_x-num="14"
        id="22">
    <mxCell style="endArrow=classic;endFill=1;html=1;strokeColor=#666666;fontSize=10;edgeStyle=orthogonalEdgeStyle;elbow=vertical" edge="1" parent="1" source="11" target="3">
        <mxGeometry relative="1" as="geometry">
            <Array as="points">
                <mxPoint x="520" y="440"/>
            </Array>
        </mxGeometry>
    </mxCell>
</object>
```

Edge routing is automatic — the script computes bend points using
obstacle-aware orthogonal routing.

---

## Full File Structure

```xml
<mxfile host="app.diagrams.net" agent="drawio-architect" version="2.0.0" type="device">
    <diagram id="diagram-1" name="Architecture">
        <mxGraphModel dx="1422" dy="794" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1600" pageHeight="1200" math="0" shadow="0">
            <root>
                <mxCell id="0"/>
                <mxCell id="1" parent="0"/>

                <!-- Groups -->
                <object label="Boot &amp; Init" id="2">
                    <mxCell style="swimlane;startSize=30;whiteSpace=wrap;html=1;fillColor=#fff7e6;strokeColor=#fa8c16;fontSize=14;fontStyle=1;swimlaneLine=1" vertex="1" parent="1">
                        <mxGeometry x="50" y="50" width="500" height="220" as="geometry"/>
                    </mxCell>
                </object>

                <!-- Code-linked node -->
                <object label="start()"
                        hedietLinkedDataV1_path="../../kernel/start.c"
                        hedietLinkedDataV1_start_line_x-num="14"
                        hedietLinkedDataV1_end_line_x-num="62"
                        id="8">
                    <mxCell style="rounded=1;whiteSpace=wrap;html=1;fillColor=#fff7e6;strokeColor=#fa8c16;fontSize=12;fontStyle=1" vertex="1" parent="2">
                        <mxGeometry x="30" y="50" width="140" height="60" as="geometry"/>
                    </mxCell>
                </object>

                <!-- Edges can also have objects -->
                <object label="mret → main" id="101">
                    <mxCell style="endArrow=classic;endFill=1;html=1;strokeColor=#666666;fontSize=10;edgeStyle=orthogonalEdgeStyle;elbow=vertical" edge="1" parent="1" source="8" target="11">
                        <mxGeometry relative="1" as="geometry">
                            <Array as="points">
                                <mxPoint x="440" y="184"/>
                            </Array>
                        </mxGeometry>
                    </mxCell>
                </object>

            </root>
        </mxGraphModel>
    </diagram>
</mxfile>
```

## ID Allocation Strategy

- IDs `0` and `1` are reserved for the root cells
- Groups: start from `2`, increment by 1
- Nodes: continue after the last group ID
- Edges: continue after the last node ID
- Container child cells (members) are also allocated from the same counter
- Keep a running counter; never reuse IDs within the same diagram

## Style Templates by Element Type

*These are generated automatically by `layout_generator.py` — you don't
need to write them manually. Only specify `type:` in YAML.*

### Service/Logic (Blue)
```
rounded=1;whiteSpace=wrap;html=1;autosizeText=1;fillColor=#e6f7ff;strokeColor=#1890ff;fontSize=12;fontStyle=1
```

### Data/Model (Green)
```
shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;size=15;autosizeText=1;fillColor=#f6ffed;strokeColor=#52c41a;fontSize=12
```

### Entry/Config (Orange)
```
rounded=1;whiteSpace=wrap;html=1;autosizeText=1;fillColor=#fff7e6;strokeColor=#fa8c16;fontSize=12;fontStyle=1
```

### External/API (Red)
```
shape=hexagon;perimeter=hexagonPerimeter2;whiteSpace=wrap;html=1;fixedSize=1;autosizeText=1;fillColor=#fff1f0;strokeColor=#f5222d;fontSize=12
```
