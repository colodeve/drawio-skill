# Style Presets — Learn, Apply, Manage

A **style preset** is a named JSON file capturing visual preferences — palette, shape vocabulary, fonts, edge style. When a preset is active, it fully replaces the built-in conventions in SKILL.md's color/shape/edge tables.

## Table of Contents

1. [Locations and Lookup Order](#locations-and-lookup-order)
2. [Applying a Preset](#applying-a-preset)
3. [Learn Flow](#learn-flow)
4. [Management Operations](#management-operations)
5. [Preset File Validation](#preset-file-validation)

---

## Locations and Lookup Order

1. `~/.drawio-architect/styles/<name>.json` — user presets (survive `git pull`)
2. `<this-skill-dir>/styles/built-in/<name>.json` — built-ins shipped with the skill (`default`, `corporate`, `handdrawn`)

A user preset shadows a built-in of the same name.

Only user presets can have `"default": true`. When the user says *"make `<built-in-name>` my default"*, copy the built-in JSON to `~/.drawio-architect/styles/<name>.json` first, then set `default: true` on the copy — leave the shipped built-in untouched.

**Name normalization:** always lowercase the user-provided name before writing or looking up files (the preset schema enforces lowercase; uppercase names will fail validation).

---

## Applying a Preset

When a preset is active, it fully replaces the built-in palette, shape keywords, edge defaults, and font for this diagram — do not mix values from the built-in color table.

### Color Lookup

For each role a shape plays (service / database / queue / gateway / error / external / security), resolve `preset.roles[role]` to a slot name, then `preset.palette[<slot>]` to the `(fillColor, strokeColor)` pair. If `roles[role]` is unset or the resolved slot is `null`, follow this fallback ladder:

1. Try the role's canonical slot (`service→primary`, `database→success`, `queue→warning`, `gateway→accent`, `error→danger`, `external→neutral`, `security→secondary`)
2. If that slot is also empty, pick the most-populated non-null slot in the preset
3. Never reach into the built-in color table — the preset is authoritative

### Decision and Container Shapes

**Decision** (rhombus) → use `preset.palette.warning`. If `warning` is empty, apply the slot-fallback ladder above starting from `warning`.

**Container** (swimlane) → use the palette slot matching the tier/grouping the container represents (e.g. a "Services" tier container uses `primary`; a "Data" tier uses `success`). If no tier signal is available, default to `primary`.

### Shape Keywords

Use `preset.shapes[role]` as the **prefix** of the vertex style string (before `whiteSpace=wrap;html=1;...`). Example: for a database role, if `preset.shapes.database = "shape=cylinder3"`, the vertex style starts `shape=cylinder3;whiteSpace=wrap;html=1;fillColor=...`.

The six named shape keys are `service`, `database`, `queue`, `decision`, `external`, `container`. Roles `gateway`, `error`, and `security` reuse `preset.shapes.service` unless the preset explicitly populates a key with their name.

### Edges

Use `preset.edges.style` as the base edge style string. Append `preset.edges.arrow`. Per-edge routing keys (`exitX/exitY/entryX/entryY/...`) are still added by the usual routing rules.

If the flow between two shapes matches a token from `preset.edges.dashedFor` (either because the user's prompt used that word, or because one end of the edge plays a role whose typical relation is "optional"), append `;dashed=1` to the edge style.

### Fonts

Append `fontFamily=<preset.font.fontFamily>;fontSize=<preset.font.fontSize>` to every vertex style. Container headers and swimlane titles additionally get `fontSize=<preset.font.titleFontSize>;fontStyle=1` when `preset.font.titleBold` is `true`.

### Extras

- `preset.extras.sketch === true` → append `sketch=1` to every vertex style and every edge style
- `preset.extras.globalStrokeWidth !== 1` → append `strokeWidth=<n>` to every vertex style and every edge style

### Interaction with Diagram-Type Presets

Diagram-type presets set structural style keywords that the user preset must preserve (e.g. ERD tables rely on `shape=table;startSize=30;container=1;childLayout=tableLayout;...`). The rule: keep the diagram-type preset's structural keywords, then layer the user preset's color / font / edge / extras on top.

---

## Learn Flow

**Triggers:** "learn", "save", "remember", or "extract" a style from a file.

### Dispatch by File Extension

- `.drawio`, `.xml` → XML path
- `.png`, `.jpg`, `.jpeg`, `.svg` → image path

### Steps

1. **Load the extraction reference** (if implementing extraction)
2. **Extract** following the appropriate procedure
3. **Normalize and build candidate** → write to `/tmp/drawio-preset-<name>.json`
4. **Render a sample** using the candidate preset
5. **Show the user:**
   - Preset summary table
   - The sample PNG
   - Provenance line
6. **Wait for approval:**
   - "save" / "looks good" → write candidate to `~/.drawio-architect/styles/<name>.json`
   - "change `<field>` to `<value>`" → edit, re-render, re-ask
   - "cancel" → delete tempfile and sample PNG

---

## Management Operations

All operations are natural language.

| User says | Agent does |
|-----------|------------|
| "list my styles", "what styles do I have" | List user and built-in presets with location, source, confidence, default flag |
| "show my `<name>` style" | Print the preset JSON + summary |
| "make `<name>` the default" | Set `default: true` on user preset; copy built-in to user dir first if needed |
| "remove default" | Clear `default: true` from whichever user preset has it |
| "delete `<name>`" | Confirm, then delete from user presets. Refuse to delete built-ins |
| "rename `<a>` to `<b>`" | Move user preset file and update `name` field inside |

---

## Preset File Validation

When loading any preset, do a lightweight structural check:
- Required top-level fields present (`name`, `version`, `palette`, `roles`, `shapes`, `font`, `edges`)
- `version === 1`
- Every populated palette slot has both `fillColor` and `strokeColor` as `#RRGGBB`
- `confidence` ∈ {`"low"`, `"medium"`, `"high"`} if present

**On validation failure:**
- **During generation:** warn the user, fall back to built-in conventions, do not mutate the file
- **During learn:** refuse to save the candidate; report which field failed
