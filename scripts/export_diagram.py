#!/usr/bin/env python3
"""
Export Diagram — Unified export wrapper for drawio diagrams.

Handles PNG/SVG/PDF export with automatic fallback.

Usage:
    python export_diagram.py --input diagram.drawio --format png --scale 2
    python export_diagram.py --input diagram.drawio --format png --preview  # no -e flag
    python export_diagram.py --input diagram.drawio --format svg
    python export_diagram.py --input diagram.drawio --browser-fallback  # URL only
"""

import os
import sys
import argparse
import subprocess
import shutil
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.encode_drawio_url import encode


def find_drawio_cli() -> Optional[str]:
    """Find draw.io CLI executable."""
    # Check PATH
    for name in ['draw.io', 'drawio']:
        if shutil.which(name):
            return name

    # macOS default path
    mac_path = "/Applications/draw.io.app/Contents/MacOS/draw.io"
    if os.path.exists(mac_path):
        return mac_path

    # Windows default path
    win_paths = [
        r"C:\Program Files\draw.io\draw.io.exe",
        r"C:\Program Files (x86)\draw.io\draw.io.exe",
    ]
    for p in win_paths:
        if os.path.exists(p):
            return f'"{p}"'

    return None


def export_with_cli(input_path: str, output_path: str, fmt: str, scale: int = 2, embed: bool = True) -> bool:
    """Export using draw.io CLI."""
    cli = find_drawio_cli()
    if not cli:
        return False

    cmd = [cli, '-x', '-f', fmt, '-s', str(scale), '-o', output_path, input_path]
    if embed and fmt == 'png':
        cmd.insert(4, '-e')

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode == 0:
            # Fix PNG IEND chunk if needed
            if embed and fmt == 'png':
                from scripts.repair_png import repair
                repair(output_path)
            return True
        else:
            print(f"Export failed: {result.stderr}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"Export error: {e}", file=sys.stderr)
        return False


def generate_browser_url(input_path: str) -> str:
    """Generate diagrams.net viewer URL as fallback."""
    with open(input_path, 'r', encoding='utf-8') as f:
        xml = f.read()
    return encode(xml)


def main():
    parser = argparse.ArgumentParser(description='Export drawio diagram')
    parser.add_argument('--input', '-i', required=True, help='Input .drawio file')
    parser.add_argument('--output', '-o', help='Output file path')
    parser.add_argument('--format', '-f', default='png', choices=['png', 'svg', 'pdf', 'jpg'])
    parser.add_argument('--scale', '-s', type=int, default=2)
    parser.add_argument('--preview', action='store_true', help='Preview mode (no -e flag)')
    parser.add_argument('--browser-fallback', action='store_true', help='Generate browser URL instead of exporting')
    args = parser.parse_args()

    input_path = os.path.abspath(args.input)

    if not os.path.exists(input_path):
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Browser fallback
    if args.browser_fallback:
        url = generate_browser_url(input_path)
        print(f"Browser URL (client-side, no upload):")
        print(url)
        sys.exit(0)

    # Determine output path
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        base = os.path.splitext(input_path)[0]
        if args.format == 'png' and not args.preview:
            output_path = f"{base}.drawio.png"
        else:
            output_path = f"{base}.{args.format}"

    # Try CLI export
    embed = not args.preview and args.format == 'png'
    success = export_with_cli(input_path, output_path, args.format, args.scale, embed)

    if success:
        print(f"Exported: {output_path}")
        sys.exit(0)
    else:
        # Fallback to browser URL
        print("draw.io CLI not available. Generating browser fallback URL...")
        url = generate_browser_url(input_path)
        print(f"Browser URL (client-side, no upload):")
        print(url)
        print(f"\nTo install CLI:")
        print("  macOS: brew install --cask drawio")
        print("  Windows: https://github.com/jgraph/drawio-desktop/releases")
        print("  Linux: https://github.com/jgraph/drawio-desktop/releases")
        sys.exit(0)


if __name__ == '__main__':
    main()
