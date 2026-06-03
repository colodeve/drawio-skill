"""Layout analysis utilities for detecting overlap and edge crossings.

This module provides:
- Layout analysis (overlap detection, edge crossing detection)
- Layout optimization algorithms (force-directed, grid)
- Layout beautification (alignment, distribution, centering)
- Token optimization for large diagrams
- Color palette and style utilities
"""

import os
import json
from typing import List, Tuple, Dict, Any, Optional, Union
from dataclasses import dataclass, field, asdict
from math import sqrt, pow, atan2, cos, sin

# Token optimization constants
PLACEHOLDER_PREFIX = "___PLACEHOLDER___"
TOKEN_SAVING_THRESHOLD = 1000  # Minimum nodes to enable token saving

# Color palette (fillColor / strokeColor)
# Used when no preset is active
COLOR_PALETTE = {
    "blue": {"fillColor": "#dae8fc", "strokeColor": "#6c8ebf", "use_for": "services, clients"},
    "green": {"fillColor": "#d5e8d4", "strokeColor": "#82b366", "use_for": "success, databases"},
    "yellow": {"fillColor": "#fff2cc", "strokeColor": "#d6b656", "use_for": "queues, decisions"},
    "orange": {"fillColor": "#ffe6cc", "strokeColor": "#d79b00", "use_for": "gateways, APIs"},
    "red": {"fillColor": "#f8cecc", "strokeColor": "#b85450", "use_for": "errors, alerts"},
    "grey": {"fillColor": "#f5f5f5", "strokeColor": "#666666", "use_for": "external/neutral"},
    "purple": {"fillColor": "#e1d5e7", "strokeColor": "#9673a6", "use_for": "security, auth"},
}

# Type-based color mapping (for code-architecture diagrams)
TYPE_COLOR_MAP = {
    "entry": {"fillColor": "#fff7e6", "strokeColor": "#fa8c16", "use_for": "Main entry, config files"},
    "service": {"fillColor": "#e6f7ff", "strokeColor": "#1890ff", "use_for": "Business logic, services"},
    "data": {"fillColor": "#f6ffed", "strokeColor": "#52c41a", "use_for": "Database, models, entities"},
    "external": {"fillColor": "#fff1f0", "strokeColor": "#f5222d", "use_for": "External APIs, third-party"},
    "controller": {"fillColor": "#f9f0ff", "strokeColor": "#722ed1", "use_for": "Controllers, UI components"},
    "infrastructure": {"fillColor": "#f0f5ff", "strokeColor": "#2f54eb", "use_for": "Middleware, utilities"},
}

# Spacing constants by diagram complexity
SPACING_PRESETS = {
    "simple": {"nodes": 5, "horizontal_gap": 200, "vertical_gap": 150},
    "medium": {"nodes": 10, "horizontal_gap": 280, "vertical_gap": 200},
    "complex": {"nodes": float('inf'), "horizontal_gap": 350, "vertical_gap": 250},
}

# Shape type keywords
SHAPE_TYPES = {
    "rectangle": "rounded=0",
    "rounded": "rounded=1",
    "ellipse": "ellipse;",
    "diamond": "rhombus;",
    "cylinder": "shape=cylinder3;",
    "swimlane": "swimlane;",
    "aws": "shape=mxgraph.aws4.resourceIcon;",
}

# Container styles
CONTAINER_STYLES = {
    "group": "group;pointerEvents=0;",
    "swimlane": "swimlane;startSize=30;",
    "custom": "container=1;pointerEvents=0;",
}


@dataclass
class Point:
    """A 2D point."""
    x: float
    y: float

    def distance_to(self, other: 'Point') -> float:
        """Calculate distance to another point."""
        return sqrt(pow(self.x - other.x, 2) + pow(self.y - other.y, 2))

    def __add__(self, other: 'Point') -> 'Point':
        return Point(self.x + other.x, self.y + other.y)

    def __sub__(self, other: 'Point') -> 'Point':
        return Point(self.x - other.x, self.y - other.y)

    def __mul__(self, scalar: float) -> 'Point':
        return Point(self.x * scalar, self.y * scalar)

    def __truediv__(self, scalar: float) -> 'Point':
        return Point(self.x / scalar, self.y / scalar)

    def magnitude(self) -> float:
        """Calculate vector magnitude."""
        return sqrt(self.x ** 2 + self.y ** 2)

    def normalize(self) -> 'Point':
        """Normalize vector to unit length."""
        mag = self.magnitude()
        if mag == 0:
            return Point(0, 0)
        return Point(self.x / mag, self.y / mag)


@dataclass
class BoundingBox:
    """A rectangular bounding box."""
    x1: float
    y1: float
    x2: float
    y2: float

    @classmethod
    def from_coords(cls, x: float, y: float, width: float, height: float) -> 'BoundingBox':
        """Create from x, y, width, height."""
        return cls(x1=x, y1=y, x2=x + width, y2=y + height)

    @property
    def width(self) -> float:
        return self.x2 - self.x1

    @property
    def height(self) -> float:
        return self.y2 - self.y1

    @property
    def center(self) -> Point:
        return Point(x=(self.x1 + self.x2) / 2, y=(self.y1 + self.y2) / 2)

    def intersects(self, other: 'BoundingBox', tolerance: float = 0.0) -> bool:
        """Check if this box intersects with another box."""
        return not (
            self.x2 + tolerance < other.x1 or
            other.x2 + tolerance < self.x1 or
            self.y2 + tolerance < other.y1 or
            other.y2 + tolerance < self.y1
        )

    def contains_point(self, point: Point) -> bool:
        """Check if box contains a point."""
        return self.x1 <= point.x <= self.x2 and self.y1 <= point.y <= self.y2

    def to_dict(self) -> Dict[str, float]:
        return {"x1": self.x1, "y1": self.y1, "x2": self.x2, "y2": self.y2}


@dataclass
class OverlapInfo:
    """Information about an overlap between two nodes."""
    node1_id: str
    node2_id: str
    overlap_area: float
    node1_box: BoundingBox
    node2_box: BoundingBox
    suggested_fix: Optional[Dict[str, Any]] = None


@dataclass
class EdgeCrossingInfo:
    """Information about an edge crossing a node."""
    edge_id: str
    node_id: str
    crossing_point: Point


@dataclass
class LayoutIssue:
    """A layout issue found in the diagram."""
    issue_type: str
    severity: str
    description: str
    node_ids: List[str] = field(default_factory=list)
    edge_ids: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class LayoutReport:
    """Complete layout analysis report."""
    total_nodes: int = 0
    total_edges: int = 0
    overlaps: List[OverlapInfo] = field(default_factory=list)
    edge_crossings: List[EdgeCrossingInfo] = field(default_factory=list)
    issues: List[LayoutIssue] = field(default_factory=list)
    page_width: int = 850
    page_height: int = 1100
    out_of_bounds: List[Dict[str, Any]] = field(default_factory=list)
    density_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary."""
        return {
            "summary": {
                "total_nodes": self.total_nodes,
                "total_edges": self.total_edges,
                "overlap_count": len(self.overlaps),
                "edge_crossing_count": len(self.edge_crossings),
                "issue_count": len(self.issues),
                "density_score": round(self.density_score, 2)
            },
            "overlaps": [
                {
                    "node1_id": o.node1_id,
                    "node2_id": o.node2_id,
                    "overlap_area": round(o.overlap_area, 2),
                    "node1_bbox": o.node1_box.to_dict(),
                    "node2_bbox": o.node2_box.to_dict(),
                    "suggested_fix": o.suggested_fix
                }
                for o in self.overlaps
            ],
            "edge_crossings": [
                {
                    "edge_id": e.edge_id,
                    "node_id": e.node_id,
                    "crossing_point": {"x": e.crossing_point.x, "y": e.crossing_point.y}
                }
                for e in self.edge_crossings
            ],
            "issues": [
                {
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "description": i.description,
                    "node_ids": i.node_ids,
                    "edge_ids": i.edge_ids,
                    "details": i.details,
                    "suggestions": i.suggestions
                }
                for i in self.issues
            ],
            "out_of_bounds": self.out_of_bounds,
            "page_dimensions": {
                "width": self.page_width,
                "height": self.page_height
            }
        }


class LayoutAnalyzer:
    """Analyzes drawio diagram layouts for issues."""

    DEFAULT_TOLERANCE = 5.0
    MIN_SPACING = 50.0
    MAX_WIDTH = 850.0
    MAX_HEIGHT = 1100.0

    def __init__(
        self,
        nodes: List[Any],
        edges: List[Any],
        page_width: int = 850,
        page_height: int = 1100
    ):
        self.nodes = nodes
        self.edges = edges
        self.page_width = page_width
        self.page_height = page_height

    def analyze(self) -> LayoutReport:
        """Perform complete layout analysis."""
        report = LayoutReport(
            total_nodes=len(self.nodes),
            total_edges=len(self.edges),
            page_width=self.page_width,
            page_height=self.page_height
        )

        report.overlaps = self.find_overlaps()
        report.edge_crossings = self.find_edge_crossings()
        report.out_of_bounds = self.check_bounds()
        report.issues = self.identify_issues(report)
        report.density_score = self.calculate_density()

        return report

    def find_overlaps(self, tolerance: float = DEFAULT_TOLERANCE) -> List[OverlapInfo]:
        """Find all overlapping node pairs."""
        overlaps = []

        for i, node1 in enumerate(self.nodes):
            for node2 in self.nodes[i + 1:]:
                if self._nodes_may_overlap(node1, node2):
                    box1 = BoundingBox.from_coords(node1.x, node1.y, node1.width, node1.height)
                    box2 = BoundingBox.from_coords(node2.x, node2.y, node2.width, node2.height)

                    if box1.intersects(box2, tolerance):
                        overlap_area = self._calculate_overlap_area(box1, box2)
                        overlap = OverlapInfo(
                            node1_id=node1.id,
                            node2_id=node2.id,
                            overlap_area=overlap_area,
                            node1_box=box1,
                            node2_box=box2,
                            suggested_fix=self._suggest_overlap_fix(node1, node2)
                        )
                        overlaps.append(overlap)

        return overlaps

    def _nodes_may_overlap(self, node1: Any, node2: Any) -> bool:
        """Quick check if two nodes might overlap."""
        parent1 = getattr(node1, 'parent', None)
        parent2 = getattr(node2, 'parent', None)
        if parent1 and parent2 and parent1 == parent2:
            return True

        dx = abs(node1.x - node2.x)
        dy = abs(node1.y - node2.y)
        return dx < (node1.width + node2.width) and dy < (node1.height + node2.height)

    def _calculate_overlap_area(self, box1: BoundingBox, box2: BoundingBox) -> float:
        """Calculate the overlap area between two boxes."""
        x_overlap = max(0, min(box1.x2, box2.x2) - max(box1.x1, box2.x1))
        y_overlap = max(0, min(box1.y2, box2.y2) - max(box1.y1, box2.y1))
        return x_overlap * y_overlap

    def _suggest_overlap_fix(self, node1: Any, node2: Any) -> Optional[Dict[str, Any]]:
        """Suggest a fix for an overlap."""
        dx = node2.x - node1.x
        dy = node2.y - node1.y

        if abs(dx) > abs(dy):
            if dx > 0:
                new_x = node1.x + node1.width + self.MIN_SPACING
                new_y = node2.y
            else:
                new_x = node1.x - node2.width - self.MIN_SPACING
                new_y = node2.y
        else:
            if dy > 0:
                new_x = node2.x
                new_y = node1.y + node1.height + self.MIN_SPACING
            else:
                new_x = node2.x
                new_y = node1.y - node2.height - self.MIN_SPACING

        return {
            "node_id": node2.id,
            "suggested_x": round(new_x, 2),
            "suggested_y": round(new_y, 2)
        }

    def find_edge_crossings(self) -> List[EdgeCrossingInfo]:
        """Find edges that cross through nodes."""
        crossings = []

        for edge in self.edges:
            source = self._find_node_by_id(edge.source_id)
            target = self._find_node_by_id(edge.target_id)

            if not source or not target:
                continue

            for node in self.nodes:
                if node.id in (edge.source_id, edge.target_id):
                    continue

                if self._edge_passes_through_node(edge, source, target, node):
                    mid_point = Point(
                        x=(source.x + target.x) / 2,
                        y=(source.y + target.y) / 2
                    )
                    crossings.append(EdgeCrossingInfo(
                        edge_id=edge.id,
                        node_id=node.id,
                        crossing_point=mid_point
                    ))

        return crossings

    def _edge_passes_through_node(self, edge: Any, source: Any, target: Any, node: Any) -> bool:
        """Check if an edge line passes through a node."""
        node_box = BoundingBox.from_coords(node.x, node.y, node.width, node.height)

        x1, y1 = source.x + source.width / 2, source.y + source.height / 2
        x2, y2 = target.x + target.width / 2, target.y + target.height / 2

        for t in [0.25, 0.5, 0.75]:
            px = x1 + t * (x2 - x1)
            py = y1 + t * (y2 - y1)
            if node_box.contains_point(Point(x=px, y=py)):
                return True

        return False

    def _find_node_by_id(self, node_id: str) -> Optional[Any]:
        """Find a node by its ID."""
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None

    def check_bounds(self) -> List[Dict[str, Any]]:
        """Check if nodes are outside page bounds."""
        out_of_bounds = []

        for node in self.nodes:
            issues = []

            if node.x < 0:
                issues.append(f"x={node.x} < 0")
            if node.y < 0:
                issues.append(f"y={node.y} < 0")
            if node.x + node.width > self.page_width:
                issues.append(f"x+width={node.x + node.width} > {self.page_width}")
            if node.y + node.height > self.page_height:
                issues.append(f"y+height={node.y + node.height} > {self.page_height}")

            if issues:
                out_of_bounds.append({
                    "node_id": node.id,
                    "node_label": node.label,
                    "position": {"x": node.x, "y": node.y, "width": node.width, "height": node.height},
                    "issues": issues
                })

        return out_of_bounds

    def identify_issues(self, report: LayoutReport) -> List[LayoutIssue]:
        """Identify all layout issues from analysis results."""
        issues = []

        if report.overlaps:
            issues.append(LayoutIssue(
                issue_type="overlap",
                severity="high",
                description=f"Found {len(report.overlaps)} overlapping node pairs",
                suggestions=["Adjust node positions to increase spacing"]
            ))

        if report.edge_crossings:
            issues.append(LayoutIssue(
                issue_type="edge_crossing",
                severity="medium",
                description=f"Found {len(report.edge_crossings)} edges crossing nodes",
                suggestions=["Reroute edges to avoid crossing nodes"]
            ))

        if report.out_of_bounds:
            issues.append(LayoutIssue(
                issue_type="out_of_bounds",
                severity="high",
                description=f"Found {len(report.out_of_bounds)} nodes outside page bounds",
                suggestions=["Move nodes within page boundaries"]
            ))

        if report.density_score > 0.8:
            issues.append(LayoutIssue(
                issue_type="high_density",
                severity="medium",
                description=f"High layout density ({report.density_score:.2f})",
                suggestions=["Consider reorganizing into groups or spreading nodes"]
            ))

        return issues

    def calculate_density(self) -> float:
        """Calculate layout density score (0.0 to 1.0)."""
        if not self.nodes:
            return 0.0

        total_node_area = sum(n.width * n.height for n in self.nodes)
        page_area = self.page_width * self.page_height

        raw_density = total_node_area / page_area

        overlap_penalty = len(self.find_overlaps()) * 0.1

        return min(1.0, raw_density + overlap_penalty)


def check_overlap(node1: Any, node2: Any, tolerance: float = 5.0) -> bool:
    """Check if two nodes overlap."""
    box1 = BoundingBox.from_coords(node1.x, node1.y, node1.width, node1.height)
    box2 = BoundingBox.from_coords(node2.x, node2.y, node2.width, node2.height)
    return box1.intersects(box2, tolerance)


def find_overlapping_nodes(nodes: List[Any], tolerance: float = 5.0) -> List[Tuple[str, str]]:
    """Find all pairs of overlapping nodes."""
    overlaps = []
    for i, node1 in enumerate(nodes):
        for j, node2 in enumerate(nodes):
            if i < j and check_overlap(node1, node2, tolerance):
                overlaps.append((node1.id, node2.id))
    return overlaps


# ====================
# Layout Optimization Algorithms
# ====================

class ForceDirectedLayout:
    """Force-directed layout algorithm for automatic node positioning."""

    def __init__(
        self,
        nodes: List[Any],
        edges: List[Any] = None,
        width: float = 1600,
        height: float = 1200,
        repulsion_strength: float = 5000.0,
        attraction_strength: float = 50.0,
        damping: float = 0.8,
        max_iterations: int = 100,
        min_movement: float = 0.1
    ):
        self.nodes = nodes
        self.edges = edges or []
        self.width = width
        self.height = height
        self.repulsion_strength = repulsion_strength
        self.attraction_strength = attraction_strength
        self.damping = damping
        self.max_iterations = max_iterations
        self.min_movement = min_movement
        self.velocities = {}  # node.id -> Point

    def _initialize_velocities(self):
        """Initialize velocity for all nodes."""
        for node in self.nodes:
            self.velocities[node.id] = Point(0, 0)

    def _calculate_repulsion(self, node1: Any, node2: Any) -> Point:
        """Calculate repulsive force between two nodes."""
        dx = node2.x - node1.x
        dy = node2.y - node1.y
        distance = sqrt(dx * dx + dy * dy)

        if distance < 1:
            distance = 1

        force_magnitude = self.repulsion_strength / (distance * distance)
        return Point(
            (dx / distance) * force_magnitude,
            (dy / distance) * force_magnitude
        )

    def _calculate_attraction(self, node1: Any, node2: Any) -> Point:
        """Calculate attractive force between connected nodes."""
        dx = node2.x - node1.x
        dy = node2.y - node1.y
        distance = sqrt(dx * dx + dy * dy)

        force_magnitude = (distance * self.attraction_strength) / 100
        return Point(
            (dx / distance) * force_magnitude,
            (dy / distance) * force_magnitude
        )

    def _apply_boundary_force(self, node: Any) -> Point:
        """Apply force to keep nodes within boundaries."""
        force = Point(0, 0)
        margin = 50

        # Left boundary
        if node.x < margin:
            force.x += (margin - node.x) * 0.5
        # Right boundary
        if node.x + node.width > self.width - margin:
            force.x -= (node.x + node.width - (self.width - margin)) * 0.5
        # Top boundary
        if node.y < margin:
            force.y += (margin - node.y) * 0.5
        # Bottom boundary
        if node.y + node.height > self.height - margin:
            force.y -= (node.y + node.height - (self.height - margin)) * 0.5

        return force

    def run(self) -> List[Any]:
        """Run the force-directed layout algorithm."""
        self._initialize_velocities()

        for iteration in range(self.max_iterations):
            total_movement = 0

            # Calculate forces
            forces = {node.id: Point(0, 0) for node in self.nodes}

            # Repulsion between all node pairs
            for i, node1 in enumerate(self.nodes):
                for j, node2 in enumerate(self.nodes):
                    if i != j:
                        repulsion = self._calculate_repulsion(node1, node2)
                        forces[node1.id] = forces[node1.id] - repulsion
                        forces[node2.id] = forces[node2.id] + repulsion

            # Attraction along edges
            for edge in self.edges:
                source = next((n for n in self.nodes if n.id == edge.source_id), None)
                target = next((n for n in self.nodes if n.id == edge.target_id), None)
                if source and target:
                    attraction = self._calculate_attraction(source, target)
                    forces[source.id] = forces[source.id] + attraction
                    forces[target.id] = forces[target.id] - attraction

            # Boundary forces
            for node in self.nodes:
                boundary_force = self._apply_boundary_force(node)
                forces[node.id] = forces[node.id] + boundary_force

            # Update positions
            for node in self.nodes:
                velocity = self.velocities[node.id]
                velocity = (velocity + forces[node.id]) * self.damping
                self.velocities[node.id] = velocity

                # Limit maximum velocity
                max_vel = 20
                if velocity.magnitude() > max_vel:
                    velocity = velocity.normalize() * max_vel

                node.x += velocity.x
                node.y += velocity.y

                total_movement += velocity.magnitude()

            # Convergence check
            if total_movement < self.min_movement * len(self.nodes):
                print(f"Force-directed layout converged after {iteration + 1} iterations")
                break

        return self.nodes


class GridLayout:
    """Grid-based layout algorithm for organized node placement."""

    def __init__(
        self,
        nodes: List[Any],
        grid_size: int = 50,
        alignment: str = "top-left",
        direction: str = "left-to-right"
    ):
        self.nodes = nodes
        self.grid_size = grid_size
        self.alignment = alignment
        self.direction = direction

    def run(self) -> List[Any]:
        """Run the grid layout algorithm."""
        if not self.nodes:
            return self.nodes

        # Calculate grid dimensions
        max_width = max(n.width for n in self.nodes) + self.grid_size
        max_height = max(n.height for n in self.nodes) + self.grid_size

        cols = int(sqrt(len(self.nodes) * max_height / max_width)) + 1
        if cols < 1:
            cols = 1
        rows = (len(self.nodes) + cols - 1) // cols

        # Calculate starting position based on alignment
        total_width = cols * max_width
        total_height = rows * max_height

        start_x, start_y = 50, 50

        if self.alignment in ["top-right", "center", "bottom-right"]:
            start_x = max(50, (1600 - total_width) / 2)
            if self.alignment == "top-right":
                start_x = max(50, 1600 - total_width - 50)

        if self.alignment in ["bottom-left", "center", "bottom-right"]:
            start_y = max(50, (1200 - total_height) / 2)
            if self.alignment in ["bottom-left", "bottom-right"]:
                start_y = max(50, 1200 - total_height - 50)

        # Place nodes on grid
        for i, node in enumerate(self.nodes):
            if self.direction == "top-to-bottom":
                col = i % cols
                row = i // cols
            else:  # left-to-right (default)
                row = i % rows
                col = i // rows

            node.x = start_x + col * max_width
            node.y = start_y + row * max_height

        return self.nodes


class LayoutBeautifier:
    """Layout beautification utilities."""

    @staticmethod
    def align_nodes(nodes: List[Any], axis: str = "both") -> List[Any]:
        """Align nodes to grid."""
        grid_size = 10

        for node in nodes:
            if axis in ["x", "both"]:
                node.x = round(node.x / grid_size) * grid_size
            if axis in ["y", "both"]:
                node.y = round(node.y / grid_size) * grid_size

        return nodes

    @staticmethod
    def distribute_horizontally(nodes: List[Any], spacing: float = 50) -> List[Any]:
        """Distribute nodes evenly horizontally."""
        if not nodes:
            return nodes

        sorted_nodes = sorted(nodes, key=lambda n: n.x)
        total_width = sum(n.width for n in sorted_nodes) + (len(nodes) - 1) * spacing
        start_x = max(50, (1600 - total_width) / 2)

        current_x = start_x
        for node in sorted_nodes:
            node.x = current_x
            current_x += node.width + spacing

        return nodes

    @staticmethod
    def distribute_vertically(nodes: List[Any], spacing: float = 50) -> List[Any]:
        """Distribute nodes evenly vertically."""
        if not nodes:
            return nodes

        sorted_nodes = sorted(nodes, key=lambda n: n.y)
        total_height = sum(n.height for n in sorted_nodes) + (len(nodes) - 1) * spacing
        start_y = max(50, (1200 - total_height) / 2)

        current_y = start_y
        for node in sorted_nodes:
            node.y = current_y
            current_y += node.height + spacing

        return nodes

    @staticmethod
    def center_nodes(nodes: List[Any]) -> List[Any]:
        """Center all nodes on the page."""
        if not nodes:
            return nodes

        min_x = min(n.x for n in nodes)
        min_y = min(n.y for n in nodes)
        max_x = max(n.x + n.width for n in nodes)
        max_y = max(n.y + n.height for n in nodes)

        center_x = (min_x + max_x) / 2
        center_y = (min_y + max_y) / 2

        page_center_x = 800
        page_center_y = 600

        offset_x = page_center_x - center_x
        offset_y = page_center_y - center_y

        for node in nodes:
            node.x += offset_x
            node.y += offset_y

        return nodes


# ====================
# Token Optimization
# ====================

class TokenOptimizer:
    """Optimize token usage for large diagrams."""

    @staticmethod
    def create_placeholders(nodes: List[Any]) -> Tuple[List[Any], Dict[str, Any]]:
        """Replace nodes with placeholders to reduce token count."""
        original_data = {}

        for i, node in enumerate(nodes):
            placeholder_id = f"{PLACEHOLDER_PREFIX}{i}"
            original_data[placeholder_id] = {
                "id": node.id,
                "label": node.label,
                "x": node.x,
                "y": node.y,
                "width": node.width,
                "height": node.height,
                "path": getattr(node, 'path', None),
                "start_line": getattr(node, 'start_line', None),
                "end_line": getattr(node, 'end_line', None)
            }

            # Simplify node for transmission
            node.label = f"Node {i}"
            node.id = placeholder_id

        return nodes, original_data

    @staticmethod
    def restore_from_placeholders(nodes: List[Any], original_data: Dict[str, Any]) -> List[Any]:
        """Restore nodes from placeholders."""
        for node in nodes:
            if node.id.startswith(PLACEHOLDER_PREFIX):
                original = original_data.get(node.id)
                if original:
                    node.id = original["id"]
                    node.label = original["label"]
                    node.x = original["x"]
                    node.y = original["y"]
                    node.width = original["width"]
                    node.height = original["height"]
                    if "path" in original:
                        setattr(node, 'path', original["path"])
                    if "start_line" in original:
                        setattr(node, 'start_line', original["start_line"])
                    if "end_line" in original:
                        setattr(node, 'end_line', original["end_line"])

        return nodes

    @staticmethod
    def estimate_token_savings(node_count: int) -> int:
        """Estimate token savings from using placeholders."""
        if node_count < TOKEN_SAVING_THRESHOLD:
            return 0

        # Rough estimate: each full node ~100 tokens, placeholder ~20 tokens
        return (node_count - TOKEN_SAVING_THRESHOLD) * 80

    @staticmethod
    def should_use_optimization(node_count: int) -> bool:
        """Determine if token optimization should be used."""
        return node_count >= TOKEN_SAVING_THRESHOLD


# ====================
# Layout Improvement API
# ====================

def improve_layout(
    nodes: List[Any],
    edges: List[Any] = None,
    algorithm: str = "force-directed",
    **kwargs
) -> List[Any]:
    """
    Improve diagram layout using specified algorithm.

    Args:
        nodes: List of diagram nodes
        edges: List of diagram edges (optional)
        algorithm: Layout algorithm to use:
            - "force-directed": Force-directed layout (default)
            - "grid": Grid-based layout
            - "align": Align nodes to grid
            - "distribute-h": Distribute horizontally
            - "distribute-v": Distribute vertically
            - "center": Center nodes
        **kwargs: Additional parameters for the algorithm

    Returns:
        Updated list of nodes
    """
    if algorithm == "force-directed":
        layout = ForceDirectedLayout(nodes, edges or [], **kwargs)
        return layout.run()

    elif algorithm == "grid":
        layout = GridLayout(nodes, **kwargs)
        return layout.run()

    elif algorithm == "align":
        axis = kwargs.get("axis", "both")
        return LayoutBeautifier.align_nodes(nodes, axis)

    elif algorithm == "distribute-h":
        spacing = kwargs.get("spacing", 50)
        return LayoutBeautifier.distribute_horizontally(nodes, spacing)

    elif algorithm == "distribute-v":
        spacing = kwargs.get("spacing", 50)
        return LayoutBeautifier.distribute_vertically(nodes, spacing)

    elif algorithm == "center":
        return LayoutBeautifier.center_nodes(nodes)

    else:
        raise ValueError(f"Unknown layout algorithm: {algorithm}")


# ====================
# Style and Color Utilities
# ====================

def get_color_by_type(node_type: str) -> Dict[str, str]:
    """Get color scheme by node type."""
    return TYPE_COLOR_MAP.get(node_type.lower(), TYPE_COLOR_MAP["service"])


def get_color_by_name(color_name: str) -> Dict[str, str]:
    """Get color scheme by color name."""
    return COLOR_PALETTE.get(color_name.lower(), COLOR_PALETTE["blue"])


def get_spacing_preset(node_count: int) -> Dict[str, int]:
    """Get spacing preset based on node count."""
    if node_count <= SPACING_PRESETS["simple"]["nodes"]:
        return SPACING_PRESETS["simple"]
    elif node_count <= SPACING_PRESETS["medium"]["nodes"]:
        return SPACING_PRESETS["medium"]
    else:
        return SPACING_PRESETS["complex"]


def get_shape_style(shape_type: str) -> str:
    """Get shape style keyword."""
    return SHAPE_TYPES.get(shape_type.lower(), SHAPE_TYPES["rectangle"])


def get_container_style(container_type: str) -> str:
    """Get container style."""
    return CONTAINER_STYLES.get(container_type.lower(), CONTAINER_STYLES["group"])


# ====================
# Edge Routing Utilities
# ====================

def calculate_entry_exit_points(node_count: int, side: str = "bottom") -> List[float]:
    """Calculate evenly distributed entry/exit points for a shape."""
    if node_count <= 1:
        return [0.5]
    
    points = []
    for i in range(node_count):
        if node_count == 2:
            points.append(0.25 + i * 0.5)
        else:
            spacing = 1.0 / (node_count + 1)
            points.append(spacing * (i + 1))
    
    return points


def create_waypoints_around_node(
    source_center: Point,
    target_center: Point,
    obstacle_box: BoundingBox,
    margin: float = 20
) -> List[Point]:
    """Create waypoints to route an edge around an obstacle node."""
    # Calculate detour points around the obstacle
    mid_x = (source_center.x + target_center.x) / 2
    mid_y = (source_center.y + target_center.y) / 2
    
    # Determine which side of the obstacle to go around
    if source_center.x < obstacle_box.x1:
        # Source is left of obstacle, go around left
        return [
            Point(obstacle_box.x1 - margin, source_center.y),
            Point(obstacle_box.x1 - margin, target_center.y)
        ]
    elif source_center.x > obstacle_box.x2:
        # Source is right of obstacle, go around right
        return [
            Point(obstacle_box.x2 + margin, source_center.y),
            Point(obstacle_box.x2 + margin, target_center.y)
        ]
    elif source_center.y < obstacle_box.y1:
        # Source is above obstacle, go around top
        return [
            Point(source_center.x, obstacle_box.y1 - margin),
            Point(target_center.x, obstacle_box.y1 - margin)
        ]
    else:
        # Source is below obstacle, go around bottom
        return [
            Point(source_center.x, obstacle_box.y2 + margin),
            Point(target_center.x, obstacle_box.y2 + margin)
        ]


# ====================
# Validation Utilities
# ====================

def validate_diagram(nodes: List[Any], edges: List[Any]) -> List[Dict[str, Any]]:
    """Validate diagram structure and return issues."""
    issues = []
    
    # Check for duplicate node IDs
    node_ids = set()
    for node in nodes:
        if node.id in node_ids:
            issues.append({
                "type": "duplicate_id",
                "severity": "high",
                "message": f"Duplicate node ID: {node.id}",
                "node_id": node.id
            })
        node_ids.add(node.id)
    
    # Check for edges with missing source/target
    for edge in edges:
        if edge.source_id not in node_ids:
            issues.append({
                "type": "missing_source",
                "severity": "high",
                "message": f"Edge {edge.id} has missing source: {edge.source_id}",
                "edge_id": edge.id
            })
        if edge.target_id not in node_ids:
            issues.append({
                "type": "missing_target",
                "severity": "high",
                "message": f"Edge {edge.id} has missing target: {edge.target_id}",
                "edge_id": edge.id
            })
    
    # Check for out-of-bounds coordinates
    for node in nodes:
        if node.x < 0 or node.y < 0:
            issues.append({
                "type": "negative_coordinate",
                "severity": "medium",
                "message": f"Node {node.id} has negative coordinates: ({node.x}, {node.y})",
                "node_id": node.id
            })
    
    return issues


# ====================
# Diagram Statistics
# ====================

def calculate_diagram_stats(nodes: List[Any], edges: List[Any]) -> Dict[str, Any]:
    """Calculate various statistics for a diagram."""
    if not nodes:
        return {
            "node_count": 0,
            "edge_count": 0,
            "avg_node_size": {"width": 0, "height": 0},
            "total_area": 0,
            "density": 0,
            "avg_connections_per_node": 0
        }
    
    total_width = sum(n.width for n in nodes)
    total_height = sum(n.height for n in nodes)
    total_area = sum(n.width * n.height for n in nodes)
    
    # Calculate connections per node
    node_connections = {}
    for edge in edges:
        node_connections[edge.source_id] = node_connections.get(edge.source_id, 0) + 1
        node_connections[edge.target_id] = node_connections.get(edge.target_id, 0) + 1
    
    avg_connections = sum(node_connections.values()) / len(nodes) if nodes else 0
    
    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "avg_node_size": {
            "width": round(total_width / len(nodes), 2),
            "height": round(total_height / len(nodes), 2)
        },
        "total_area": round(total_area, 2),
        "avg_connections_per_node": round(avg_connections, 2)
    }
