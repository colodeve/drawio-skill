# Export Commands and Fallback Strategies

This document describes how to export diagrams to various formats and fallback options when tools are unavailable.

**推荐使用统一导出脚本** `scripts/export_diagram.py`（自动处理 CLI 检测、PNG 修复、fallback）。

## 快速导出

```bash
# 推荐：使用统一导出脚本（自动检测 CLI、修复 PNG、fallback）
python3 scripts/export_diagram.py --input diagram.drawio --format png --scale 2

# Preview 模式（无 -e，用于 vision 自检查）
python3 scripts/export_diagram.py --input diagram.drawio --format png --preview

# SVG / PDF
python3 scripts/export_diagram.py --input diagram.drawio --format svg
python3 scripts/export_diagram.py --input diagram.drawio --format pdf

# 仅生成浏览器 URL（无 CLI 时）
python3 scripts/export_diagram.py --input diagram.drawio --browser-fallback
```

---

## 手动导出（高级）

### Export Modes

There are **two** export modes:

- **Preview / self-check** — no `-e`. Output `diagram.png`. Required for vision self-check; using `-e` here triggers a 400 "Could not process image" error from vision APIs.
- **Final / deliverable** — pass `-e`. Output `diagram.drawio.png`. The embedded XML keeps the file editable in draw.io.

### Command Reference

#### Preview PNG (step 4, before self-check) — NO `-e`

```bash
draw.io -x -f png -s 2 -o diagram.png input.drawio
```

#### Final PNG (step 7, after user approval) — WITH `-e`, double extension

```bash
draw.io -x -f png -e -s 2 -o diagram.drawio.png input.drawio
```

#### macOS — full path (if not in PATH)

```bash
/Applications/draw.io.app/Contents/MacOS/draw.io -x -f png -s 2 -o diagram.png input.drawio
/Applications/draw.io.app/Contents/MacOS/draw.io -x -f png -e -s 2 -o diagram.drawio.png input.drawio
```

#### Windows

```bash
"C:\Program Files\draw.io\draw.io.exe" -x -f png -e -s 2 -o diagram.drawio.png input.drawio
```

#### Linux (headless)

```bash
export HOME=${HOME:-/tmp}
xvfb-run -a --server-args="-screen 0 1280x1024x24" \
  draw.io -x -f png -e -s 2 -o diagram.drawio.png input.drawio --disable-gpu
```

Running as root (CI / Docker)? Append `--no-sandbox` AT THE END.

#### SVG Export (final)

```bash
draw.io -x -f svg -e -o diagram.svg input.drawio
```

#### PDF Export (final)

```bash
draw.io -x -f pdf -e -o diagram.pdf input.drawio
```

---

## Post-Export PNG Repair

draw.io CLI truncates the IEND chunk when emitting `-e` PNGs — the file ends with the 4-byte IEND length field but the `IEND` type + CRC (8 bytes) are missing. Result: vision APIs return 400 "Could not process image" and strict PNG decoders error out. SVG/PDF are unaffected.

**统一导出脚本已自动处理。** 手动修复命令：

```bash
python3 scripts/repair_png.py diagram.drawio.png
```

The script's `endswith(IEND)` guard makes it a no-op once draw.io fixes the bug upstream — safe to run unconditionally.

---

## Browser Fallback (no CLI needed)

When the draw.io desktop CLI is unavailable, generate a client-side viewer URL:

```bash
python3 scripts/encode_drawio_url.py input.drawio
# or
python3 scripts/export_diagram.py --input diagram.drawio --browser-fallback
```

Prints a `https://viewer.diagrams.net/...` URL with the diagram XML deflate-compressed and base64-encoded into the URL fragment. The fragment (after `#`) is never sent to the server, so nothing is uploaded — the diagram opens client-side for viewing and editing.

---

## Fallback Chain

When tools are unavailable, degrade gracefully:

| Scenario | Behavior |
|----------|----------|
| draw.io CLI available | Use `export_diagram.py` — 自动导出 + PNG 修复 |
| draw.io CLI missing, Python available | `export_diagram.py` 自动生成 browser URL |
| draw.io CLI missing, Python missing | Generate `.drawio` XML only; instruct user to open in draw.io desktop or diagrams.net manually |
| draw.io CLI crashes / no output in macOS sandbox isolation | Treat CLI as unavailable in-sandbox; use browser fallback / XML-only; ask user to run CLI exports in a non-sandboxed host environment |
| Vision unavailable for self-check | Skip self-check; proceed directly to showing user the exported PNG |
| Export fails (Chromium/display issues) | On Linux, retry with `xvfb-run -a`; if still failing, deliver `.drawio` XML and suggest manual export |
| Export fails on Linux server (headless) | Try in order: (1) `xvfb-run -a`, (2) append `--no-sandbox` at the very end if root, (3) add `--disable-gpu`, (4) `export HOME=/tmp`, (5) install apt deps (`libgtk-3-0 libnotify4 libnss3 libgbm1 libasound2t64` etc.), (6) fall back to tomkludy/drawio-renderer Docker |

---

## Checking draw.io Availability

```bash
# Try short command first
if command -v draw.io &>/dev/null; then
  DRAWIO="draw.io"
elif [ -f "/Applications/draw.io.app/Contents/MacOS/draw.io" ]; then
  DRAWIO="/Applications/draw.io.app/Contents/MacOS/draw.io"
else
  echo "draw.io not found — install from https://github.com/jgraph/drawio-desktop/releases"
fi
```

---

## Key Flags

| Flag | Description |
|------|-------------|
| `-x` | Export mode (required) |
| `-f` | Format: `png`, `svg`, `pdf`, `jpg` |
| `-e` | Embed diagram XML in output — exported file remains editable in draw.io |
| `-s` | Scale: `1`, `2`, `3` (2 recommended for PNG) |
| `-o` | Output file path |
| `-b` | Border width around diagram (default: 0, recommend 10) |
| `-t` | Transparent background (PNG only) |
| `--page-index 0` | Export specific page (default: all) |

**Important**: Skip `-e` for the preview PNG used in self-check — `-e` PNGs have a truncated IEND chunk that vision APIs reject. For final PNG export, keep `-e` and run `scripts/repair_png.py`.
