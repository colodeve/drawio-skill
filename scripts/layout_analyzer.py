#!/usr/bin/env python3
"""
Layout Analyzer - Analyze and optimize drawio diagram layouts.

This script analyzes drawio diagrams for:
- Node overlaps
- Edge crossings through nodes
- Nodes outside page bounds
- High layout density

And provides optimization features:
- Force-directed layout
- Grid layout
- Layout beautification (alignment, distribution, centering)
- Token optimization for large diagrams

Usage:
    python layout_analyzer.py --drawio examples/diagram.drawio
    python layout_analyzer.py --drawio examples/diagram.drawio --optimize --algorithm force-directed
    python layout_analyzer.py --drawio examples/diagram.drawio --output report.json
"""

import os
import sys
import argparse
import json
from typing import List, Dict, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.xml_parser import XmlParser, DiagramData
from scripts.utils.layout_utils import (
    LayoutAnalyzer, LayoutReport,
    ForceDirectedLayout, GridLayout, LayoutBeautifier,
    TokenOptimizer, improve_layout,
    get_color_by_type, get_spacing_preset, validate_diagram, calculate_diagram_stats,
    COLOR_PALETTE, TYPE_COLOR_MAP, SPACING_PRESETS
)


class DiagramLayoutAnalyzer:
    """Analyzer for drawio diagram layouts."""

    def __init__(self, drawio_file: str):
        self.drawio_file = os.path.abspath(drawio_file)
        self.parser = XmlParser(drawio_file)
        self.data: Optional[DiagramData] = None
        self.analyzer: Optional[LayoutAnalyzer] = None

    def run(self) -> LayoutReport:
        """Run the complete layout analysis."""
        print(f"Loading drawio file: {self.drawio_file}")

        if not os.path.exists(self.drawio_file):
            raise FileNotFoundError(f"File not found: {self.drawio_file}")

        self.data = self.parser.load(self.drawio_file)

        print(f"Found {len(self.data.nodes)} nodes and {len(self.data.edges)} edges")

        self.analyzer = LayoutAnalyzer(
            nodes=self.data.nodes,
            edges=self.data.edges,
            page_width=self.data.page_width,
            page_height=self.data.page_height
        )

        return self.analyzer.analyze()

    def auto_fix(self, max_iterations: int = 3) -> LayoutReport:
        """Auto-fix layout issues iteratively."""
        if self.data is None:
            self.data = self.parser.load(self.drawio_file)

        if self.analyzer is None:
            self.analyzer = LayoutAnalyzer(
                nodes=self.data.nodes,
                edges=self.data.edges,
                page_width=self.data.page_width,
                page_height=self.data.page_height
            )

        for i in range(max_iterations):
            report = self.analyzer.analyze()
            if not report.overlaps and not report.out_of_bounds and not report.edge_crossings and not report.issues:
                print(f"Layout clean after {i} fix rounds")
                return report

            print(f"Auto-fix round {i+1}/{max_iterations}: {len(report.overlaps)} overlaps, {len(report.out_of_bounds)} out-of-bounds")

            # Fix overlaps by pushing nodes apart
            for overlap in report.overlaps:
                fix = overlap.suggested_fix
                if fix:
                    node_id = fix.get('node_id')
                    for node in self.data.nodes:
                        if node.id == node_id:
                            node.x = fix.get('suggested_x', node.x)
                            node.y = fix.get('suggested_y', node.y)
                            break

            # Fix out-of-bounds by moving inside
            for oob in report.out_of_bounds:
                node_id = oob.get('node_id')
                for node in self.data.nodes:
                    if node.id == node_id:
                        if node.x < 0:
                            node.x = 50
                        if node.y < 0:
                            node.y = 50
                        if node.x + node.width > self.data.page_width:
                            node.x = self.data.page_width - node.width - 50
                        if node.y + node.height > self.data.page_height:
                            node.y = self.data.page_height - node.height - 50
                        break

            # Update analyzer with fixed positions
            self.analyzer = LayoutAnalyzer(
                nodes=self.data.nodes,
                edges=self.data.edges,
                page_width=self.data.page_width,
                page_height=self.data.page_height
            )

        return self.analyzer.analyze()

    def optimize(self, algorithm: str = "force-directed", **kwargs) -> bool:
        """Optimize the layout using specified algorithm."""
        if self.data is None:
            self.data = self.parser.load(self.drawio_file)

        print(f"Applying {algorithm} layout optimization...")

        try:
            improve_layout(
                nodes=self.data.nodes,
                edges=self.data.edges,
                algorithm=algorithm,
                **kwargs
            )
            print(f"Layout optimization completed successfully")
            return True
        except Exception as e:
            print(f"Layout optimization failed: {e}")
            return False

    def save(self, output_file: Optional[str] = None):
        """Save the optimized diagram."""
        if self.data is None:
            raise ValueError("No diagram data to save")

        target_file = output_file or self.drawio_file
        self.parser.save(target_file, self.data)
        print(f"Diagram saved to: {target_file}")


def analyze_drawio(drawio_file: str, output_file: Optional[str] = None) -> Dict[str, Any]:
    """Convenience function to analyze a drawio file."""
    analyzer = DiagramLayoutAnalyzer(drawio_file)
    report = analyzer.run()

    result = report.to_dict()
    
    # Add validation and statistics
    result["validation"] = validate_diagram(analyzer.data.nodes, analyzer.data.edges)
    result["statistics"] = calculate_diagram_stats(analyzer.data.nodes, analyzer.data.edges)

    if output_file:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Report saved to: {output_file}")

    return result


def optimize_drawio(
    drawio_file: str,
    algorithm: str = "force-directed",
    output_file: Optional[str] = None,
    **kwargs
) -> bool:
    """Optimize a drawio file's layout."""
    analyzer = DiagramLayoutAnalyzer(drawio_file)
    analyzer.run()  # Load data

    if analyzer.optimize(algorithm, **kwargs):
        analyzer.save(output_file)
        return True
    return False


def print_report(report: Dict[str, Any]) -> None:
    """Print a formatted report to console."""
    summary = report.get("summary", {})

    print("\n" + "=" * 60)
    print("LAYOUT ANALYSIS REPORT")
    print("=" * 60)

    print(f"\nSummary:")
    print(f"  Total nodes:        {summary.get('total_nodes', 0)}")
    print(f"  Total edges:        {summary.get('total_edges', 0)}")
    print(f"  Overlaps found:     {summary.get('overlap_count', 0)}")
    print(f"  Edge crossings:     {summary.get('edge_crossing_count', 0)}")
    print(f"  Issues found:       {summary.get('issue_count', 0)}")
    print(f"  Density score:      {summary.get('density_score', 0.0)}")

    dimensions = report.get("page_dimensions", {})
    print(f"\nPage dimensions: {dimensions.get('width', 850)} x {dimensions.get('height', 1100)}")

    if report.get("overlaps"):
        print(f"\n--- Overlapping Nodes ---")
        for i, overlap in enumerate(report["overlaps"][:5], 1):
            print(f"  {i}. {overlap['node1_id']} <-> {overlap['node2_id']}")
            print(f"     Overlap area: {overlap['overlap_area']:.2f} sq px")
            if overlap.get("suggested_fix"):
                fix = overlap["suggested_fix"]
                print(f"     Suggested fix: Move node {fix.get('node_id')} to ({fix.get('suggested_x')}, {fix.get('suggested_y')})")
        if len(report["overlaps"]) > 5:
            print(f"  ... and {len(report['overlaps']) - 5} more overlaps")

    if report.get("out_of_bounds"):
        print(f"\n--- Out of Bounds ---")
        for i, node in enumerate(report["out_of_bounds"][:5], 1):
            print(f"  {i}. {node['node_id']} ({node.get('node_label', 'unknown')})")
            for issue in node.get("issues", []):
                print(f"     - {issue}")
        if len(report["out_of_bounds"]) > 5:
            print(f"  ... and {len(report['out_of_bounds']) - 5} more out-of-bounds nodes")

    if report.get("issues"):
        print(f"\n--- Issues ---")
        for i, issue in enumerate(report["issues"], 1):
            print(f"  {i}. [{issue['severity'].upper()}] {issue['description']}")
            for suggestion in issue.get("suggestions", []):
                print(f"     - {suggestion}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Analyze and optimize drawio diagram layout"
    )
    parser.add_argument(
        "--drawio", "-d",
        required=True,
        help="Path to the drawio file"
    )
    parser.add_argument(
        "--output", "-o",
        help="Output JSON report file or optimized drawio file"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    parser.add_argument(
        "--check-overlaps",
        action="store_true",
        help="Check for node overlaps"
    )
    parser.add_argument(
        "--check-bounds",
        action="store_true",
        help="Check for out-of-bounds nodes"
    )
    parser.add_argument(
        "--density-threshold",
        type=float,
        default=0.8,
        help="Density threshold for warnings (default: 0.8)"
    )
    
    # Optimization arguments
    parser.add_argument(
        "--optimize", "-O",
        action="store_true",
        help="Optimize the layout"
    )
    parser.add_argument(
        "--algorithm", "-a",
        default="force-directed",
        choices=[
            "force-directed", "grid", "align", 
            "distribute-h", "distribute-v", "center"
        ],
        help="Layout optimization algorithm"
    )
    parser.add_argument(
        "--grid-size",
        type=int,
        default=50,
        help="Grid size for grid layout"
    )
    parser.add_argument(
        "--alignment",
        default="top-left",
        choices=["top-left", "top-right", "center", "bottom-left", "bottom-right"],
        help="Alignment for grid layout"
    )
    parser.add_argument(
        "--spacing",
        type=float,
        default=50.0,
        help="Spacing for distribution algorithms"
    )
    parser.add_argument(
        "--repulsion",
        type=float,
        default=5000.0,
        help="Repulsion strength for force-directed layout"
    )
    parser.add_argument(
        "--attraction",
        type=float,
        default=50.0,
        help="Attraction strength for force-directed layout"
    )

    args = parser.parse_args()

    try:
        if args.optimize:
            # Run optimization
            algo_kwargs = {}
            
            if args.algorithm == "force-directed":
                algo_kwargs = {
                    "repulsion_strength": args.repulsion,
                    "attraction_strength": args.attraction
                }
            elif args.algorithm == "grid":
                algo_kwargs = {
                    "grid_size": args.grid_size,
                    "alignment": args.alignment
                }
            elif args.algorithm in ["distribute-h", "distribute-v"]:
                algo_kwargs = {
                    "spacing": args.spacing
                }
            elif args.algorithm == "align":
                algo_kwargs = {
                    "axis": "both"
                }
            
            result = optimize_drawio(
                args.drawio,
                algorithm=args.algorithm,
                output_file=args.output,
                **algo_kwargs
            )

            if result:
                print("\nLayout optimization completed successfully!")
                # Run analysis after optimization to show improvements
                analysis_result = analyze_drawio(args.drawio)
                if args.verbose:
                    print_report(analysis_result)
                else:
                    summary = analysis_result.get("summary", {})
                    print(f"Final state: {summary.get('overlap_count', 0)} overlaps, {summary.get('edge_crossing_count', 0)} crossings")
            else:
                print("Layout optimization failed")
                sys.exit(1)
        else:
            # Run analysis only
            result = analyze_drawio(args.drawio, args.output)

            summary = result.get("summary", {})

            if args.verbose:
                print_report(result)
            else:
                total_issues = summary.get("overlap_count", 0) + summary.get("edge_crossing_count", 0)

                if total_issues > 0:
                    print(f"\nFound {total_issues} layout issues:")
                    if summary.get("overlap_count", 0) > 0:
                        print(f"  - {summary['overlap_count']} overlapping node pairs")
                    if summary.get("edge_crossing_count", 0) > 0:
                        print(f"  - {summary['edge_crossing_count']} edge crossings")
                    print(f"\nUse --verbose for detailed report or --output for JSON output.")
                    print(f"Use --optimize to automatically fix layout issues.")
                else:
                    print("No layout issues found.")

            if args.check_overlaps and result.get("overlaps"):
                sys.exit(1)
            if args.check_bounds and result.get("out_of_bounds"):
                sys.exit(1)
            if summary.get("density_score", 0) > args.density_threshold:
                print(f"\nWarning: High layout density ({summary['density_score']:.2f})")
                print("Consider using --optimize to improve layout.")

        sys.exit(0)

    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
