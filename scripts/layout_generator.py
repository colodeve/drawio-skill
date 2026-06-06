#!/usr/bin/env python3
"""
Layout Generator — Automatic layout engine for drawio diagrams.

Reads structured YAML/JSON and outputs .drawio XML with computed coordinates.
Replaces manual coordinate calculation in SKILL.md.

Usage:
    python layout_generator.py --input structure.yaml --output diagram.drawio
    python layout_generator.py --input structure.json --existing diagram.drawio --patch
    python layout_generator.py --stdin --output diagram.drawio
"""

import os
import sys
import argparse
import json
import yaml
import math
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils.layout_utils import (
    LayoutAnalyzer, LayoutBeautifier,
    ForceDirectedLayout, GridLayout,
    get_color_by_type, get_shape_style,
    check_overlap, create_waypoints_around_node, calculate_entry_exit_points,
    BoundingBox, Point
)


# Layout constants
GRID_SIZE = 10
DEFAULT_ELEM_WIDTH = 140
DEFAULT_ELEM_HEIGHT = 60
DEFAULT_GROUP_HEADER = 30
DEFAULT_GROUP_PADDING = 30
DEFAULT_GROUP_TOP_PAD = 50
DEFAULT_ELEM_GAP_H = 60
DEFAULT_ELEM_GAP_V = 90
DEFAULT_GROUP_GAP_H = 120
DEFAULT_GROUP_GAP_V = 160
DEFAULT_ROUTE_TRACK_SPACING = 16.0
DEFAULT_CANVAS_MARGIN = 50
DEFAULT_PAGE_WIDTH = 1600
DEFAULT_PAGE_HEIGHT = 1200
EDGE_CLEARANCE = 20

# Map node type to drawio shape
SHAPE_MAP = {
    'entry': 'rounded=1',
    'config': 'rounded=1',
    'service': 'rounded=1',
    'logic': 'rounded=1',
    'data': 'rounded=1',
    'model': 'rounded=1',
    'database': 'shape=cylinder3;boundedLbl=1;backgroundOutline=1;size=15',
    'external': 'shape=hexagon;perimeter=hexagonPerimeter2;fixedSize=1',
    'api': 'shape=hexagon;perimeter=hexagonPerimeter2;fixedSize=1',
    'controller': 'rounded=1',
    'ui': 'rounded=1',
    'infrastructure': 'rounded=1',
    'middleware': 'rounded=1',
    'gateway': 'rounded=1',
    'queue': 'rounded=1',
    'decision': 'rhombus',
}


@dataclass
class NodeDef:
    """Node definition from structured input."""
    id: str
    label: str
    node_type: str
    group: Optional[str] = None
    path: str = ""
    lines: List[int] = field(default_factory=lambda: [0, 0])
    description: str = ""
    # Child text cells for detail display inside a container
    members: List[str] = field(default_factory=list)
    # Container mode: use swimlane+stackLayout to hold member text cells
    container: bool = False
    # Semantic scale: 1.0 = normal, 1.5 = more prominent, 0.7 = compact
    scale: float = 1.0
    # Computed fields
    x: float = 0
    y: float = 0
    width: float = DEFAULT_ELEM_WIDTH
    height: float = DEFAULT_ELEM_HEIGHT
    parent: Optional[str] = None
    # True if this node was parsed from existing diagram (not newly created)
    _preserved: bool = False


@dataclass
class EdgeDef:
    """Edge definition from structured input."""
    source_id: str
    target_id: str
    label: str = ""
    path: str = ""
    lines: List[int] = field(default_factory=lambda: [0, 0])
    style: str = "solid"
    animation: str = ""


@dataclass
class GroupDef:
    """Group/Swimlane definition."""
    name: str
    label: str = ""
    group_type: str = "service"
    path: str = ""
    # Computed fields
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


@dataclass
class DiagramDef:
    """Complete diagram definition."""
    nodes: List[NodeDef] = field(default_factory=list)
    edges: List[EdgeDef] = field(default_factory=list)
    groups: List[GroupDef] = field(default_factory=list)
    notes: List[Dict] = field(default_factory=list)
    layout_algorithm: str = "layered"
    layout_direction: str = "top-to-bottom"
    preserve_existing: bool = False
    page_width: int = DEFAULT_PAGE_WIDTH
    page_height: int = DEFAULT_PAGE_HEIGHT
    spacing_h: int = DEFAULT_ELEM_GAP_H
    spacing_v: int = DEFAULT_ELEM_GAP_V
    route_spacing: float = DEFAULT_ROUTE_TRACK_SPACING
    edge_animation: str = ""
    grid_size: int = GRID_SIZE
    auto_size: bool = True


@dataclass
class EdgeRoute:
    edge: EdgeDef
    points: List[Point]
    source_point: Point
    target_point: Point
    orientation: str
    exit_x: float
    exit_y: float
    entry_x: float
    entry_y: float
    source_perimeter_spacing: int
    target_perimeter_spacing: int


@dataclass
class EdgeSegment:
    route: EdgeRoute
    index: int
    orientation: str
    coord: float
    start: float
    end: float


def _node_height(node: NodeDef) -> float:
    """Compute actual node height. Container nodes are taller due to member text cells.
    scale multiplies the base size for semantic prominence."""
    if node.container and node.members:
        base = 30.0 + len(node.members) * 22.0 + 10.0
    else:
        base = float(DEFAULT_ELEM_HEIGHT)
    return base * node.scale


def _node_width(node: NodeDef) -> float:
    """Node width. Container width should be wider to fit member text.
    scale multiplies the base size for semantic prominence."""
    if node.container and node.members:
        base = max(float(DEFAULT_ELEM_WIDTH), 160.0)
    else:
        base = float(DEFAULT_ELEM_WIDTH)
    return base * node.scale


def _compute_node_port_point(node: NodeDef, x_factor: float, y_factor: float) -> Point:
    """Compute an absolute perimeter point for a node edge port."""
    return Point(x=node.x + node.width * x_factor, y=node.y + node.height * y_factor)


def _get_edge_port_factors(
    src_node: NodeDef,
    tgt_node: NodeDef,
    src_total: int,
    src_idx: int,
    tgt_total: int,
    tgt_idx: int
) -> Tuple[float, float, float, float, str]:
    """Choose initial port factors and routing orientation for an edge.

    When source and target are vertically aligned (abs(dx) < 10), prefer
    bottom→top routing so the edge goes straight down/up.
    """
    sx = src_node.x + src_node.width / 2
    sy = src_node.y + src_node.height / 2
    tx = tgt_node.x + tgt_node.width / 2
    ty = tgt_node.y + tgt_node.height / 2
    dx = tx - sx
    dy = ty - sy

    # Vertical alignment: prefer bottom→top (or top→bottom) straight routing
    if abs(dx) < 10 and abs(dy) > 0:
        # Force vertical routing: exit from bottom, enter from top
        src_exit_x = 0.5
        src_exit_y = 1.0 if dy > 0 else 0.0
        tgt_entry_x = 0.5
        tgt_entry_y = 0.0 if dy > 0 else 1.0
        return src_exit_x, src_exit_y, tgt_entry_x, tgt_entry_y, "vertical"

    if abs(dx) >= abs(dy):
        src_exit_y = 1.0 if dy >= 0 else 0.0
        tgt_entry_y = 0.0 if dy >= 0 else 1.0
        src_exit_x = (calculate_entry_exit_points(src_total)[src_idx]
                      if src_total > 1 else 0.5)
        tgt_entry_x = (calculate_entry_exit_points(tgt_total)[tgt_idx]
                       if tgt_total > 1 else 0.5)
        return src_exit_x, src_exit_y, tgt_entry_x, tgt_entry_y, "horizontal"

    src_exit_x = 1.0 if dx >= 0 else 0.0
    tgt_entry_x = 0.0 if dx >= 0 else 1.0
    src_exit_y = (calculate_entry_exit_points(src_total)[src_idx]
                  if src_total > 1 else 0.5)
    tgt_entry_y = (calculate_entry_exit_points(tgt_total)[tgt_idx]
                   if tgt_total > 1 else 0.5)
    return src_exit_x, src_exit_y, tgt_entry_x, tgt_entry_y, "vertical"


def _build_edge_routes(
    diagram_def: DiagramDef,
    source_edge_counts: Dict[str, int],
    target_edge_counts: Dict[str, int]
) -> List[EdgeRoute]:
    node_obj_map = {n.id: n for n in diagram_def.nodes}
    routes: List[EdgeRoute] = []
    source_edge_indices: Dict[str, int] = {}
    target_edge_indices: Dict[str, int] = {}

    for edge in diagram_def.edges:
        src_node = node_obj_map.get(edge.source_id)
        tgt_node = node_obj_map.get(edge.target_id)
        src_idx = source_edge_indices.get(edge.source_id, 0)
        tgt_idx = target_edge_indices.get(edge.target_id, 0)
        src_total = source_edge_counts.get(edge.source_id, 1)
        tgt_total = target_edge_counts.get(edge.target_id, 1)

        if not src_node or not tgt_node:
            continue

        exit_x, exit_y, entry_x, entry_y, orientation = _get_edge_port_factors(
            src_node, tgt_node, src_total, src_idx, tgt_total, tgt_idx
        )

        source_point = _compute_node_port_point(src_node, exit_x, exit_y)
        target_point = _compute_node_port_point(tgt_node, entry_x, entry_y)

        if orientation == "horizontal":
            bend = Point(x=target_point.x, y=source_point.y)
        else:
            bend = Point(x=source_point.x, y=target_point.y)

        source_sp = 10 + src_idx * 5
        target_sp = 10 + tgt_idx * 5
        routes.append(EdgeRoute(
            edge=edge,
            points=[source_point, bend, target_point],
            source_point=source_point,
            target_point=target_point,
            orientation=orientation,
            exit_x=exit_x,
            exit_y=exit_y,
            entry_x=entry_x,
            entry_y=entry_y,
            source_perimeter_spacing=source_sp,
            target_perimeter_spacing=target_sp
        ))

        source_edge_indices[edge.source_id] = src_idx + 1
        target_edge_indices[edge.target_id] = tgt_idx + 1

    return routes


def _create_route_segments(routes: List[EdgeRoute]) -> List[EdgeSegment]:
    segments: List[EdgeSegment] = []

    for route in routes:
        for idx in range(len(route.points) - 1):
            a = route.points[idx]
            b = route.points[idx + 1]
            if abs(a.y - b.y) < 1e-6:
                orientation = "horizontal"
                coord = a.y
                start, end = sorted((a.x, b.x))
            elif abs(a.x - b.x) < 1e-6:
                orientation = "vertical"
                coord = a.x
                start, end = sorted((a.y, b.y))
            else:
                continue

            segments.append(EdgeSegment(
                route=route,
                index=idx,
                orientation=orientation,
                coord=coord,
                start=start,
                end=end
            ))

    return segments


def _apply_axis_offsets(segments: List[EdgeSegment], track_spacing: float = DEFAULT_ROUTE_TRACK_SPACING):
    grouped: Dict[int, List[EdgeSegment]] = {}
    for segment in segments:
        key = int(round(segment.coord))
        grouped.setdefault(key, []).append(segment)

    for same_coord_segments in grouped.values():
        same_coord_segments.sort(key=lambda seg: seg.start)
        clusters: List[List[EdgeSegment]] = []
        cluster: List[EdgeSegment] = []
        last_end = -float('inf')

        for seg in same_coord_segments:
            if cluster and seg.start > last_end:
                clusters.append(cluster)
                cluster = []
            cluster.append(seg)
            last_end = max(last_end, seg.end)

        if cluster:
            clusters.append(cluster)

        for cluster in clusters:
            if len(cluster) <= 1:
                continue

            for idx, segment in enumerate(cluster):
                if idx == 0:
                    offset = 0.0
                else:
                    level = (idx + 1) // 2
                    offset = level * track_spacing
                    if idx % 2 == 0:
                        offset = -offset

                route = segment.route
                # Skip offsetting source/target perimeter point segments
                # (index 0 and last index connect to source/target points)
                # Only offset inner segments between bend points
                total_segments = len(route.points) - 1
                if total_segments > 2 and (segment.index == 0 or segment.index == total_segments - 1):
                    continue

                start_point = route.points[segment.index]
                end_point = route.points[segment.index + 1]

                if segment.orientation == "horizontal":
                    route.points[segment.index] = Point(x=start_point.x, y=start_point.y + offset)
                    route.points[segment.index + 1] = Point(x=end_point.x, y=end_point.y + offset)
                else:
                    route.points[segment.index] = Point(x=start_point.x + offset, y=start_point.y)
                    route.points[segment.index + 1] = Point(x=end_point.x + offset, y=end_point.y)


def _fix_hediet_path(path: str) -> str:
    """vscode-drawio's CodePosition.deserialize uses path.join(drawioFilePath, path).
    Since drawioFilePath includes the filename, that filename acts as an extra directory
    level. We always prepend ../ to compensate.

    YAML paths should be relative to the drawio file's DIRECTORY (not the file):
      - drawio at root, source at kernel/main.c → YAML: kernel/main.c → XML: ../kernel/main.c
      - drawio in diagrams/, source at kernel/main.c → YAML: ../kernel/main.c → XML: ../../kernel/main.c
    """
    if not path:
        return path
    return "../" + path


def _segment_intersects_box(p1: Point, p2: Point, box: BoundingBox, clearance: float = 0) -> bool:
    """Check if a line segment intersects a rectangle (axis-aligned), with optional clearance."""
    x1 = box.x1 - clearance
    y1 = box.y1 - clearance
    x2 = box.x2 + clearance
    y2 = box.y2 + clearance

    if (x1 <= p1.x <= x2 and y1 <= p1.y <= y2):
        return True
    if (x1 <= p2.x <= x2 and y1 <= p2.y <= y2):
        return True

    if abs(p1.y - p2.y) < 1e-6:
        y = p1.y
        if not (y1 <= y <= y2):
            return False
        seg_min, seg_max = sorted((p1.x, p2.x))
        return not (seg_max <= x1 or seg_min >= x2)
    elif abs(p1.x - p2.x) < 1e-6:
        x = p1.x
        if not (x1 <= x <= x2):
            return False
        seg_min, seg_max = sorted((p1.y, p2.y))
        return not (seg_max <= y1 or seg_min >= y2)

    return False


def _build_obstacle_boxes(diagram_def: DiagramDef, clearance: float) -> List[dict]:
    """Build a list of expanded obstacle boxes from nodes and groups.

    Groups are tracked; callers can filter out 'home groups' of source/target.
    """
    boxes = []
    # Map group name → set of node ids in that group
    group_members: Dict[str, set] = {}
    for node in diagram_def.nodes:
        if node.group:
            group_members.setdefault(node.group, set()).add(node.id)

    for node in diagram_def.nodes:
        boxes.append({
            "id": node.id,
            "box": BoundingBox.from_coords(node.x, node.y, node.width, node.height),
            "cx": node.x + node.width / 2,
            "cy": node.y + node.height / 2,
        })
    for group in diagram_def.groups:
        members = group_members.get(group.name, set())
        boxes.append({
            "id": f"group:{group.name}",
            "box": BoundingBox.from_coords(group.x, group.y, group.width, group.height),
            "cx": group.x + group.width / 2,
            "cy": group.y + group.height / 2,
            "is_group": True,
            "members": members,
        })
    return boxes


def _is_home_obstacle(ob: dict, src_id: str, tgt_id: str) -> bool:
    """Check if an obstacle is a group that contains source or target."""
    if not ob.get("is_group"):
        return False
    members = ob.get("members", set())
    return src_id in members or tgt_id in members


def _route_intersects_boxes(route: EdgeRoute, boxes: List[dict],
                            src_id: str, tgt_id: str,
                            clearance: float = 0) -> List[dict]:
    """Return all boxes whose expanded region the route intersects."""
    hits = []
    for ob in boxes:
        if ob["id"] == src_id or ob["id"] == tgt_id:
            continue
        if _is_home_obstacle(ob, src_id, tgt_id):
            continue
        obs_box = ob["box"]
        for a, b in zip(route.points, route.points[1:]):
            if _segment_intersects_box(a, b, obs_box, clearance):
                hits.append(ob)
                break
    return hits


def _try_lshape_route(src: Point, tgt: Point, orientation: str) -> List[Point]:
    if orientation == "horizontal":
        bend = Point(x=tgt.x, y=src.y)
    else:
        bend = Point(x=src.x, y=tgt.y)
    # If bend coincides with src or tgt (straight line), return straight route
    if (abs(bend.x - src.x) < 1 and abs(bend.y - src.y) < 1) or \
       (abs(bend.x - tgt.x) < 1 and abs(bend.y - tgt.y) < 1):
        return [src, tgt]
    return [src, bend, tgt]


def _flatten_route_points_for_edge(src: Point, tgt: Point, obstacles: List[dict],
                                    src_id: str, tgt_id: str,
                                    orientation: str,
                                    diagram_def: Optional[DiagramDef] = None) -> List[Point]:
    """Find the simplest clear path between src and tgt avoiding all obstacles.

    Tries:
      1. Direct L-shaped (one 90° bend) — current orientation
      2. Flipped L-shaped — other orientation
      3. If both blocked: push the bend point into the nearest clear gap
      4. If still blocked: A* grid search (last resort)
    """
    cand = _try_lshape_route(src, tgt, orientation)
    if not _any_segment_hits_boxes(cand, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
        return cand

    other = "vertical" if orientation == "horizontal" else "horizontal"
    cand2 = _try_lshape_route(src, tgt, other)
    if not _any_segment_hits_boxes(cand2, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
        return cand2

    pushed = _push_bend_outside(src, tgt, obstacles, src_id, tgt_id, orientation)
    if not _any_segment_hits_boxes(pushed, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
        return pushed

    # All L/Z attempts blocked — use A* grid search as fallback
    astar_result = _astar_route(src, tgt, obstacles, src_id, tgt_id, diagram_def)
    if astar_result:
        return astar_result

    return pushed


def _astar_route(src: Point, tgt: Point, obstacles: List[dict],
                 src_id: str, tgt_id: str,
                 diagram_def: Optional[DiagramDef] = None) -> Optional[List[Point]]:
    """Simple obstacle-aware router for when L/Z shapes are blocked.

    Finds the bounding box of all blocking obstacles and routes around
    the shortest side, producing a clean 2-bend (or 3-bend) Z/U-shaped path.
    """
    find_obs = [ob for ob in obstacles
                if ob["id"] not in (src_id, tgt_id)
                and not _is_home_obstacle(ob, src_id, tgt_id)]
    if not find_obs:
        return None

    # Compute min bounding box that covers all blocking obstacles
    min_x = min(ob["box"].x1 - EDGE_CLEARANCE for ob in find_obs)
    min_y = min(ob["box"].y1 - EDGE_CLEARANCE for ob in find_obs)
    max_x = max(ob["box"].x2 + EDGE_CLEARANCE for ob in find_obs)
    max_y = max(ob["box"].y2 + EDGE_CLEARANCE for ob in find_obs)

    # Check if dest is above/below/left/right of the blocked zone
    src_above = src.y < min_y
    src_below = src.y > max_y
    src_left = src.x < min_x
    src_right = src.x > max_x
    tgt_above = tgt.y < min_y
    tgt_below = tgt.y > max_y
    tgt_left = tgt.x < min_x
    tgt_right = tgt.x > max_x

    # Route above: go up above blocked zone, then across, then down
    route_y = min(min_y - EDGE_CLEARANCE * 2, tgt.y - EDGE_CLEARANCE * 2)
    route_x = max(max_x + EDGE_CLEARANCE * 2, tgt.x + EDGE_CLEARANCE * 2)

    candidates = []

    # Above: horizontal across from src.x to tgt.x at min_y - clearance
    if not src_above:
        bypass_y = min_y - EDGE_CLEARANCE * 2
        cand = [src, Point(x=src.x, y=bypass_y),
                Point(x=tgt.x, y=bypass_y), tgt]
        if not _any_segment_hits_boxes(cand, obstacles, src_id, tgt_id, 0):
            candidates.append((abs(bypass_y - src.y), cand))

    # Below: horizontal across at max_y + clearance
    if not src_below:
        bypass_y = max_y + EDGE_CLEARANCE * 2
        cand = [src, Point(x=src.x, y=bypass_y),
                Point(x=tgt.x, y=bypass_y), tgt]
        if not _any_segment_hits_boxes(cand, obstacles, src_id, tgt_id, 0):
            candidates.append((abs(bypass_y - src.y), cand))

    # Left: vertical across at min_x - clearance
    if not src_left:
        bypass_x = min_x - EDGE_CLEARANCE * 2
        cand = [src, Point(x=bypass_x, y=src.y),
                Point(x=bypass_x, y=tgt.y), tgt]
        if not _any_segment_hits_boxes(cand, obstacles, src_id, tgt_id, 0):
            candidates.append((abs(bypass_x - src.x), cand))

    # Right: vertical across at max_x + clearance
    if not src_right:
        bypass_x = max_x + EDGE_CLEARANCE * 2
        cand = [src, Point(x=bypass_x, y=src.y),
                Point(x=bypass_x, y=tgt.y), tgt]
        if not _any_segment_hits_boxes(cand, obstacles, src_id, tgt_id, 0):
            candidates.append((abs(bypass_x - src.x), cand))

    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    return None


def _any_segment_hits_boxes(points: List[Point], obstacles: List[dict],
                             src_id: str, tgt_id: str, clearance: float) -> bool:
    """Check if any segment of the point path hits any expanded obstacle."""
    for ob in obstacles:
        if ob["id"] == src_id or ob["id"] == tgt_id:
            continue
        if _is_home_obstacle(ob, src_id, tgt_id):
            continue
        obs_box = ob["box"]
        for a, b in zip(points, points[1:]):
            if _segment_intersects_box(a, b, obs_box, clearance):
                return True
    return False


def _push_bend_outside(src: Point, tgt: Point, obstacles: List[dict],
                        src_id: str, tgt_id: str,
                        orientation: str) -> List[Point]:
    """Push the route to the nearest clear gap, returning a proper orthogonal Z-shaped path.

    Returns 4 points [src, push_a, push_b, tgt] forming two orthogonal bends,
    never a diagonal segment.
    """
    if orientation == "horizontal":
        sy, ty = src.y, tgt.y
        sx, tx = src.x, tgt.x
        blocked_y = _get_blocked_intervals_along_segment(
            Point(x=sx, y=sy), Point(x=tx, y=sy),
            obstacles, src_id, tgt_id, "y", EDGE_CLEARANCE)
        blocked_x = _get_blocked_intervals_along_segment(
            Point(x=tx, y=sy), Point(x=tx, y=ty),
            obstacles, src_id, tgt_id, "x", EDGE_CLEARANCE)
        blocked_y2 = _get_blocked_intervals_along_segment(
            Point(x=sx, y=ty), Point(x=tx, y=ty),
            obstacles, src_id, tgt_id, "y", EDGE_CLEARANCE)

        blocked_y = _merge_intervals(blocked_y + blocked_y2)
        blocked_x = _merge_intervals(blocked_x)

        clear_y = _nearest_clear(blocked_y, sy, ty, EDGE_CLEARANCE)
        if clear_y is not None:
            pts = [src, Point(x=src.x, y=clear_y),
                   Point(x=tgt.x, y=clear_y), tgt]
            if not _any_segment_hits_boxes(pts, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
                return pts

        clear_x = _nearest_clear(blocked_x, sx, tx, EDGE_CLEARANCE)
        if clear_x is not None:
            pts = [src, Point(x=clear_x, y=src.y),
                   Point(x=clear_x, y=tgt.y), tgt]
            if not _any_segment_hits_boxes(pts, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
                return pts

        fallback_y = sy if abs(ty - sy) > 0 else sy + 80
        return [src, Point(x=src.x, y=fallback_y),
                Point(x=tgt.x, y=fallback_y), tgt]

    sy, ty = src.y, tgt.y
    sx, tx = src.x, tgt.x
    blocked_x = _get_blocked_intervals_along_segment(
        Point(x=sx, y=sy), Point(x=sx, y=ty),
        obstacles, src_id, tgt_id, "x", EDGE_CLEARANCE)
    blocked_y = _get_blocked_intervals_along_segment(
        Point(x=sx, y=ty), Point(x=tx, y=ty),
        obstacles, src_id, tgt_id, "y", EDGE_CLEARANCE)
    blocked_x2 = _get_blocked_intervals_along_segment(
        Point(x=tx, y=sy), Point(x=tx, y=ty),
        obstacles, src_id, tgt_id, "x", EDGE_CLEARANCE)

    blocked_x = _merge_intervals(blocked_x + blocked_x2)
    blocked_y = _merge_intervals(blocked_y)

    clear_x = _nearest_clear(blocked_x, sx, tx, EDGE_CLEARANCE)
    if clear_x is not None:
        pts = [src, Point(x=clear_x, y=src.y),
               Point(x=clear_x, y=tgt.y), tgt]
        if not _any_segment_hits_boxes(pts, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
            return pts

    clear_y = _nearest_clear(blocked_y, sy, ty, EDGE_CLEARANCE)
    if clear_y is not None:
        pts = [src, Point(x=src.x, y=clear_y),
               Point(x=tgt.x, y=clear_y), tgt]
        if not _any_segment_hits_boxes(pts, obstacles, src_id, tgt_id, EDGE_CLEARANCE):
            return pts

    fallback_x = sx if abs(tx - sx) > 0 else sx + 80
    return [src, Point(x=fallback_x, y=src.y),
            Point(x=fallback_x, y=tgt.y), tgt]


def _get_blocked_intervals_along_segment(p1: Point, p2: Point, obstacles: List[dict],
                                           src_id: str, tgt_id: str,
                                           axis: str, clearance: float) -> List[tuple]:
    """For a straight segment, return the blocked intervals on the perpendicular axis."""
    intervals = []
    for ob in obstacles:
        if ob["id"] == src_id or ob["id"] == tgt_id:
            continue
        if _is_home_obstacle(ob, src_id, tgt_id):
            continue
        box = ob["box"]
        bx1 = box.x1 - clearance
        by1 = box.y1 - clearance
        bx2 = box.x2 + clearance
        by2 = box.y2 + clearance

        if axis == "y":
            seg_x1, seg_x2 = sorted((p1.x, p2.x))
            if seg_x2 <= bx1 or seg_x1 >= bx2:
                continue
            intervals.append((by1, by2))
        else:  # axis == "x"
            seg_y1, seg_y2 = sorted((p1.y, p2.y))
            if seg_y2 <= by1 or seg_y1 >= by2:
                continue
            intervals.append((bx1, bx2))
    return intervals


def _merge_intervals(intervals: List[tuple]) -> List[tuple]:
    """Merge overlapping intervals."""
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda x: x[0])
    merged = [sorted_iv[0]]
    for iv in sorted_iv[1:]:
        if iv[0] <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], iv[1]))
        else:
            merged.append(iv)
    return merged


def _nearest_clear(blocked: List[tuple], start: float, end: float, clearance: float) -> Optional[float]:
    """Find the nearest clear coordinate between start and end outside all blocked intervals.

    Enforces a minimum coordinate of `clearance` to prevent negative-position bend points.
    """
    if not blocked:
        return None
    low = max(clearance, min(start, end) - clearance * 3)
    high = max(start, end) + clearance * 3

    candidates = []

    # Check below the first blocked interval
    cand = blocked[0][0] - clearance
    if low <= cand <= high:
        if min(start, end) - clearance <= cand <= max(start, end) + clearance:
            candidates.append((abs(cand - start), cand))

    # Check above the last blocked interval
    cand = blocked[-1][1] + clearance
    if low <= cand <= high:
        if min(start, end) - clearance <= cand <= max(start, end) + clearance:
            candidates.append((abs(cand - start), cand))

    # Check gaps between intervals
    for i in range(len(blocked) - 1):
        gap_start = blocked[i][1]
        gap_end = blocked[i + 1][0]
        if gap_end - gap_start >= clearance * 2.5:
            mid = (gap_start + gap_end) / 2
            if low <= mid <= high:
                candidates.append((abs(mid - start), mid))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return candidates[0][1]


def _avoid_obstacles(routes: List[EdgeRoute], diagram_def: DiagramDef):
    """Simplify edge routes around all obstacles with clearance.

    Builds the full obstacle set and finds ONE simple clear path
    (L-shaped, pushed L-shaped, or A* as last resort).
    """
    obstacles = _build_obstacle_boxes(diagram_def, EDGE_CLEARANCE)

    for route in routes:
        src_id = route.edge.source_id
        tgt_id = route.edge.target_id
        src = route.source_point
        tgt = route.target_point

        new_pts = _flatten_route_points_for_edge(
            src, tgt, obstacles, src_id, tgt_id,
            route.orientation, diagram_def
        )
        route.points = new_pts


def _refine_edge_routes(routes: List[EdgeRoute], diagram_def: DiagramDef):
    _avoid_obstacles(routes, diagram_def)
    _ensure_orthogonal_routes(routes)
    segments = _create_route_segments(routes)
    horizontal_segments = [seg for seg in segments if seg.orientation == "horizontal"]
    vertical_segments = [seg for seg in segments if seg.orientation == "vertical"]
    _apply_axis_offsets(horizontal_segments, diagram_def.route_spacing)
    _apply_axis_offsets(vertical_segments, diagram_def.route_spacing)
    _ensure_orthogonal_routes(routes)
    _verify_edge_clearance(routes, diagram_def)


def _verify_edge_clearance(routes: List[EdgeRoute], diagram_def: DiagramDef, min_clearance: float = 10):
    """Ensure all bend points maintain min_clearance distance from obstacles.
    
    After orthogonal fixup inserts new bend points, those points might end up
    too close to node/group boundaries. This function pushes them to a safe
    distance.
    """
    obstacles = _build_obstacle_boxes(diagram_def, EDGE_CLEARANCE)

    for route in routes:
        src_id = route.edge.source_id
        tgt_id = route.edge.target_id
        src = route.source_point
        tgt = route.target_point
        pts = route.points

        for i in range(1, len(pts) - 1):
            p = pts[i]
            # Skip if this point is at the exact same position as src or tgt
            # (it's the entry/exit perim point, not a real bend)
            if (abs(p.x - src.x) < 1 and abs(p.y - src.y) < 1) or \
               (abs(p.x - tgt.x) < 1 and abs(p.y - tgt.y) < 1):
                continue
            for ob in obstacles:
                if ob["id"] == src_id or ob["id"] == tgt_id:
                    continue
                if _is_home_obstacle(ob, src_id, tgt_id):
                    continue
                box = ob["box"]
                # Check distance from point to each edge of the box
                if box.x1 <= p.x <= box.x2:
                    dist_top = abs(p.y - box.y1)
                    dist_bot = abs(p.y - box.y2)
                    if dist_top < min_clearance:
                        p.y = box.y1 - min_clearance
                    elif dist_bot < min_clearance:
                        p.y = box.y2 + min_clearance
                if box.y1 <= p.y <= box.y2:
                    dist_left = abs(p.x - box.x1)
                    dist_right = abs(p.x - box.x2)
                    if dist_left < min_clearance:
                        p.x = box.x1 - min_clearance
                    elif dist_right < min_clearance:
                        p.x = box.x2 + min_clearance


def _ensure_orthogonal_routes(routes: List[EdgeRoute]):
    """Fix any non-orthogonal segments by inserting bend points.

    After _apply_axis_offsets modifies bend points, adjacent segments can
    become diagonal. This function inserts extra bend points to restore
    orthogonal routing.
    """
    for route in routes:
        pts = route.points
        changed = True
        while changed:
            changed = False
            i = 1
            while i < len(pts) - 1:
                prev = pts[i - 1]
                curr = pts[i]
                nxt = pts[i + 1]
                dx1 = abs(curr.x - prev.x)
                dy1 = abs(curr.y - prev.y)
                dx2 = abs(nxt.x - curr.x)
                dy2 = abs(nxt.y - curr.y)

                diag1 = dx1 > 0.5 and dy1 > 0.5
                diag2 = dx2 > 0.5 and dy2 > 0.5

                if diag1 and not diag2:
                    new_pt = Point(x=curr.x, y=prev.y)
                    pts.insert(i, new_pt)
                    changed = True
                    i += 2
                elif not diag1 and diag2:
                    new_pt = Point(x=nxt.x, y=curr.y)
                    pts.insert(i + 1, new_pt)
                    changed = True
                    i += 2
                elif diag1 and diag2:
                    new_pt = Point(x=curr.x, y=prev.y)
                    pts.insert(i, new_pt)
                    changed = True
                    i += 2
                else:
                    i += 1


class LayoutEngine:
    """Main layout engine."""

    def __init__(self, diagram_def: DiagramDef):
        self.def_ = diagram_def
        self.node_map: Dict[str, NodeDef] = {}
        self.group_map: Dict[str, GroupDef] = {}
        self._build_maps()

    def _build_maps(self):
        for n in self.def_.nodes:
            self.node_map[n.id] = n
        for g in self.def_.groups:
            self.group_map[g.name] = g

    def _position_notes(self):
        """Position notes at the bottom of their group, after node layout.

        Expands group height to contain notes so they don't overflow.
        Coordinates are stored relative to the group parent.
        """
        margin = DEFAULT_ELEM_GAP_V
        for note in self.def_.notes:
            group_name = note.get("group")
            if group_name and group_name in self.group_map:
                g = self.group_map[group_name]
                children = [n for n in self.def_.nodes if n.group == group_name]
                max_bottom = g.y + DEFAULT_GROUP_TOP_PAD
                for child in children:
                    child_bottom = child.y + child.height
                    if child_bottom > max_bottom:
                        max_bottom = child_bottom
                nw = note.get("width", 200)
                nh = note.get("height", 80)
                # Coordinates relative to group parent
                ny = max_bottom - g.y + margin
                nx = DEFAULT_GROUP_PADDING
                note.update({"_x": nx, "_y": ny, "width": nw, "height": nh})
                note_bottom_abs = g.y + ny + nh
                if note_bottom_abs > g.y + g.height:
                    g.height = int(note_bottom_abs - g.y + margin)
            else:
                note.setdefault("_x", 50)
                note.setdefault("_y", 50)
            note.setdefault("width", 200)
            note.setdefault("height", 80)

    def compute_layout(self) -> DiagramDef:
        """Compute coordinates for all nodes and groups."""
        # First, ensure all groups exist
        self._ensure_groups()

        # Layout based on algorithm
        algo = self.def_.layout_algorithm
        if self.def_.preserve_existing and algo != "preserve":
            algo = "preserve"

        if algo == "layered":
            self._layout_layered()
        elif algo == "grid":
            self._layout_grid()
        elif algo == "hub":
            self._layout_hub()
        elif algo == "flow":
            self._layout_flow()
        elif algo == "tree":
            self._layout_tree()
        elif algo == "preserve":
            self._layout_preserve()
        else:
            self._layout_layered()  # fallback

        # Position notes at group bottom (before overlap fix so notes don't fight)
        self._position_notes()

        # Fix overlaps
        self._fix_overlaps()

        # Align to grid
        self._align_to_grid()

        # Expand canvas if auto sizing is enabled
        self._auto_resize_canvas()

        return self.def_

    def _ensure_groups(self):
        """Create implicit groups from node.group references."""
        for node in self.def_.nodes:
            if node.group and node.group not in self.group_map:
                g = GroupDef(
                    name=node.group,
                    label=node.group.replace("_", " ").title(),
                    group_type="service"
                )
                self.def_.groups.append(g)
                self.group_map[g.name] = g

    def _layout_layered(self):
        """Layered layout: groups arranged in layers top-to-bottom."""
        direction = self.def_.layout_direction
        groups = self.def_.groups

        if not groups:
            # No groups: place all nodes in a single layer
            self._layout_nodes_layered(self.def_.nodes, direction)
            return

        # Calculate group sizes first
        self._calculate_group_sizes()

        # Arrange groups in layers
        if direction in ("top-to-bottom", "bottom-to-top"):
            self._arrange_groups_vertical(groups)
        else:
            self._arrange_groups_horizontal(groups)

        # Position nodes within each group
        for group in groups:
            group_nodes = [n for n in self.def_.nodes if n.group == group.name]
            self._layout_nodes_in_group(group_nodes, group)

    def _layout_grid(self):
        """Grid layout: nodes arranged in a grid."""
        nodes = self.def_.nodes
        if not nodes:
            return

        spacing_h = max(DEFAULT_ELEM_GAP_H, self.def_.spacing_h)
        spacing_v = max(DEFAULT_ELEM_GAP_V, self.def_.spacing_v)

        n = len(nodes)
        if n <= 2:
            cols = n
        else:
            cols = max(2, int(n ** 0.5))
        x = DEFAULT_CANVAS_MARGIN
        y = DEFAULT_CANVAS_MARGIN

        for i, node in enumerate(nodes):
            col = i % cols
            row = i // cols
            # Use per-row accumulation instead of node's own width × col
            if col == 0:
                node.x = x
            else:
                # Find position after previous node in same row
                prev_idx = i - 1
                if prev_idx >= 0 and nodes[prev_idx].y == y + row * (_node_height(nodes[0]) + spacing_v):
                    node.x = nodes[prev_idx].x + _node_width(nodes[prev_idx]) + spacing_h
                else:
                    node.x = x + col * _node_width(node) + col * spacing_h
            node.y = y + row * (_node_height(node) + spacing_v)
            node.width = _node_width(node)
            node.height = _node_height(node)

    def _layout_hub(self):
        """Hub layout: central node with satellites."""
        # Find the node with most connections
        edge_count = {}
        for e in self.def_.edges:
            edge_count[e.source_id] = edge_count.get(e.source_id, 0) + 1
            edge_count[e.target_id] = edge_count.get(e.target_id, 0) + 1

        center_id = max(edge_count, key=edge_count.get) if edge_count else None
        if not center_id or center_id not in self.node_map:
            # Fallback to layered
            self._layout_layered()
            return

        center = self.node_map[center_id]
        cw = _node_width(center)
        ch = _node_height(center)
        cx = self.def_.page_width / 2 - cw / 2
        cy = self.def_.page_height / 3 - ch / 2
        center.x = cx
        center.y = cy
        center.width = cw
        center.height = ch

        # Position satellites in a circle
        satellites = [n for n in self.def_.nodes if n.id != center_id]
        n_sats = len(satellites)
        # Compute radius: at least 200px, ensure no overlap between satellites
        avg_sat_w = sum(_node_width(n) for n in satellites) / max(n_sats, 1)
        min_radius = max(200, n_sats * avg_sat_w / 3.14159)
        radius = min(max(200, min_radius), 600)  # Bounded between 200-600
        angle_step = 2 * 3.14159 / max(n_sats, 1)

        for i, node in enumerate(satellites):
            angle = i * angle_step - 3.14159 / 2  # Start from top
            sw = _node_width(node)
            sh = _node_height(node)
            node.x = cx + radius * math.cos(angle) - sw / 2
            node.y = cy + radius * math.sin(angle) - sh / 2
            node.width = sw
            node.height = sh

    def _layout_flow(self):
        """Flow layout: left-to-right or top-to-bottom pipeline."""
        self._layout_layered()

    def _layout_tree(self):
        """Tree layout: hierarchical tree structure."""
        # Build parent-child relationships from edges
        children_map: Dict[str, List[str]] = {}
        parent_map: Dict[str, str] = {}

        for edge in self.def_.edges:
            if edge.source_id not in children_map:
                children_map[edge.source_id] = []
            children_map[edge.source_id].append(edge.target_id)
            parent_map[edge.target_id] = edge.source_id

        # Find roots (nodes without parents)
        roots = [n for n in self.def_.nodes if n.id not in parent_map]
        if not roots:
            roots = [self.def_.nodes[0]] if self.def_.nodes else []

        # Position tree recursively
        visited: Set[str] = set()

        def position_subtree(node_id: str, x: float, y: float, level: int) -> float:
            if node_id in visited:
                return x  # Cycle detected, skip
            visited.add(node_id)

            node = self.node_map.get(node_id)
            if not node:
                return x

            node.x = x
            node.y = y + level * (int(_node_height(node)) + DEFAULT_ELEM_GAP_V)

            children = children_map.get(node_id, [])
            if not children:
                return x + _node_width(node) + DEFAULT_ELEM_GAP_H

            child_x = x
            for child_id in children:
                child_x = position_subtree(child_id, child_x, y, level + 1)

            # Center parent over children
            first_child = self.node_map.get(children[0])
            last_child = self.node_map.get(children[-1])
            if first_child and last_child:
                node.x = (first_child.x + last_child.x) / 2

            return child_x

        current_x = DEFAULT_CANVAS_MARGIN
        for root in roots:
            current_x = position_subtree(root.id, current_x, DEFAULT_CANVAS_MARGIN, 0)

    def _layout_preserve(self):
        """Preserve existing coordinates. Only position new nodes.

        Groups and their child positions are kept intact (not re-laid-out).
        Only the group dimensions are recalculated so swimlanes render properly.
        New nodes are detected by missing positions and placed near connected nodes.
        """
        spacing_h = max(DEFAULT_ELEM_GAP_H, self.def_.spacing_h)

        # Track which nodes are new (no existing position data)
        # Priority: _preserved flag > explicit non-zero position > zero position
        new_node_ids = set()
        for node in self.def_.nodes:
            if node._preserved:
                continue
            # If node has explicit non-default position and was parsed from 
            # an existing diagram (width/height differ from defaults), preserve it
            w = _node_width(node)
            h = _node_height(node)
            has_explicit_pos = abs(node.x) > 1 or abs(node.y) > 1
            has_custom_size = abs(node.width - w) > 5 or abs(node.height - h) > 5
            if has_explicit_pos:
                node._preserved = True
                continue
            if abs(node.x) < 1 and abs(node.y) < 1:
                new_node_ids.add(node.id)

        # Only recalculate group dimensions in preserve mode, NOT node positions
        if self.def_.groups:
            for group in self.def_.groups:
                group_children = [n for n in self.def_.nodes
                                  if n.group == group.name and n.id not in new_node_ids]
                new_in_group = [n for n in self.def_.nodes
                                if n.group == group.name and n.id in new_node_ids]
                if group_children:
                    group.width = max(group.width, max(n.x + n.width for n in group_children)
                                      - group.x + DEFAULT_GROUP_PADDING)
                    group.height = max(group.height, max(n.y + n.height for n in group_children)
                                       - group.y + DEFAULT_GROUP_PADDING + 20)

        # Position new nodes near connected existing nodes
        for node in self.def_.nodes:
            if node.id in new_node_ids:
                connected = []
                for edge in self.def_.edges:
                    if edge.source_id == node.id and edge.target_id in self.node_map:
                        connected.append(self.node_map[edge.target_id])
                    elif edge.target_id == node.id and edge.source_id in self.node_map:
                        connected.append(self.node_map[edge.source_id])

                if connected:
                    ref = connected[0]
                    node.x = ref.x + _node_width(ref) + spacing_h
                    node.y = ref.y
                else:
                    node.x = DEFAULT_CANVAS_MARGIN
                    node.y = DEFAULT_CANVAS_MARGIN
                node.width = _node_width(node)
                node.height = _node_height(node)

    def _calculate_group_sizes(self):
        """Calculate width/height for each group based on children."""
        spacing_h = max(DEFAULT_ELEM_GAP_H, self.def_.spacing_h)
        spacing_v = max(DEFAULT_ELEM_GAP_V, self.def_.spacing_v)

        for group in self.def_.groups:
            children = [n for n in self.def_.nodes if n.group == group.name]
            if not children:
                group.width = 300
                group.height = 200
                continue

            # Calculate needed cols/rows
            num_cols = min(3, len(children))
            num_rows = (len(children) + num_cols - 1) // num_cols

            # Build per-row node list to compute actual row heights
            rows: List[List[NodeDef]] = [[] for _ in range(num_rows)]
            for i, child in enumerate(children):
                col = i % num_cols
                row = i // num_cols
                rows[row].append(child)

            # Max node width per row (for content_width)
            max_node_w = max(_node_width(c) for c in children)

            content_width = (num_cols * max_node_w +
                           (num_cols - 1) * spacing_h +
                           2 * DEFAULT_GROUP_PADDING)

            # Compute actual height: each row takes the height of its tallest node
            total_height = DEFAULT_GROUP_TOP_PAD
            for row_nodes in rows:
                row_h = max(_node_height(n) for n in row_nodes)
                total_height += row_h
            total_height += (num_rows - 1) * spacing_v + 20

            group.width = max(300, int(content_width))
            group.height = max(150, int(total_height))

    def _arrange_groups_vertical(self, groups: List[GroupDef]):
        """Arrange groups top-to-bottom."""
        spacing_h = max(DEFAULT_GROUP_GAP_H, self.def_.spacing_h)
        spacing_v = max(DEFAULT_GROUP_GAP_V, self.def_.spacing_v)

        cols = max(1, int(len(groups) ** 0.5))
        x = DEFAULT_CANVAS_MARGIN
        y = DEFAULT_CANVAS_MARGIN
        max_row_height = 0

        for i, group in enumerate(groups):
            col = i % cols
            if col == 0 and i > 0:
                x = DEFAULT_CANVAS_MARGIN
                y += max_row_height + spacing_v
                max_row_height = 0

            group.x = x
            group.y = y
            x += group.width + spacing_h
            max_row_height = max(max_row_height, group.height)

    def _arrange_groups_horizontal(self, groups: List[GroupDef]):
        """Arrange groups left-to-right."""
        x = DEFAULT_CANVAS_MARGIN
        y = DEFAULT_CANVAS_MARGIN

        for group in groups:
            group.x = x
            group.y = y
            x += group.width + DEFAULT_GROUP_GAP_H

    def _layout_nodes_in_group(self, nodes: List[NodeDef], group: GroupDef):
        """Layout nodes inside a group using row-major order.

        Each row's Y position is computed from the actual max height of
        nodes in the previous row, so container nodes with many members
        don't overflow or overlap.
        """
        if not nodes:
            return

        spacing_h = max(DEFAULT_ELEM_GAP_H, self.def_.spacing_h)
        spacing_v = max(DEFAULT_ELEM_GAP_V, self.def_.spacing_v)

        num_cols = min(3, len(nodes))
        num_rows = (len(nodes) + num_cols - 1) // num_cols

        # Build per-row node lists
        rows: List[List[NodeDef]] = [[] for _ in range(num_rows)]
        for i, n in enumerate(nodes):
            rows[i // num_cols].append(n)

        current_y = group.y + DEFAULT_GROUP_TOP_PAD
        for row_idx, row_nodes in enumerate(rows):
            # Compute actual height for this row
            row_h = max(_node_height(n) for n in row_nodes)
            total_w = sum(_node_width(n) for n in row_nodes) + spacing_h * (len(row_nodes) - 1)
            # Center row within group if narrower than group width
            row_offset_x = max(DEFAULT_GROUP_PADDING,
                               (group.width - total_w - 2 * DEFAULT_GROUP_PADDING) // 2)
            if row_offset_x < DEFAULT_GROUP_PADDING:
                row_offset_x = DEFAULT_GROUP_PADDING

            # Calculate row x positions using cumulative width (not node's own width × col)
            current_x = group.x + row_offset_x
            for col_idx, node in enumerate(row_nodes):
                node.x = current_x
                node.y = current_y
                node.width = _node_width(node)
                node.height = _node_height(node)
                current_x += node.width + spacing_h

            current_y += row_h + spacing_v

    def _layout_nodes_layered(self, nodes: List[NodeDef], direction: str):
        """Layout nodes without groups in layers.

        Uses per-row/col max node height so container nodes don't overflow.
        """
        if not nodes:
            return

        spacing_h = max(DEFAULT_ELEM_GAP_H, self.def_.spacing_h)
        spacing_v = max(DEFAULT_ELEM_GAP_V, self.def_.spacing_v)

        cols = min(4, len(nodes))
        num_rows = (len(nodes) + cols - 1) // cols

        # Build per-row node lists
        rows: List[List[NodeDef]] = [[] for _ in range(num_rows)]
        for i, n in enumerate(nodes):
            rows[i // cols].append(n)

        if direction in ("top-to-bottom", "bottom-to-top"):
            current_y = DEFAULT_CANVAS_MARGIN
            for row_nodes in rows:
                row_h = max(_node_height(n) for n in row_nodes)
                # Use cumulative x positioning
                cx = DEFAULT_CANVAS_MARGIN
                for node in row_nodes:
                    node.x = cx
                    node.y = current_y
                    node.width = _node_width(node)
                    node.height = _node_height(node)
                    cx += node.width + spacing_h
                current_y += row_h + spacing_v
        else:
            current_x = DEFAULT_CANVAS_MARGIN
            for row_nodes in rows:
                row_w = max(_node_width(n) for n in row_nodes)
                # Use cumulative y positioning
                cy = DEFAULT_CANVAS_MARGIN
                for node in row_nodes:
                    node.x = current_x
                    node.y = cy
                    node.width = _node_width(node)
                    node.height = _node_height(node)
                    cy += node.height + spacing_v
                current_x += row_w + spacing_h

    def _fix_overlaps(self, max_iterations: int = 10):
        """Fix overlapping nodes by pushing them apart.

        Uses multiple iterations to converge; each pass checks ALL pairs.
        Falls back to canvas expansion if overlaps persist.
        """
        overlap_tolerance = max(GRID_SIZE, self.def_.spacing_h // 6)
        for iteration in range(max_iterations):
            overlaps_found = False
            for i, n1 in enumerate(self.def_.nodes):
                for n2 in self.def_.nodes[i + 1:]:
                    if self._nodes_overlap(n1, n2, overlap_tolerance):
                        self._push_apart(n1, n2)
                        overlaps_found = True
            if not overlaps_found:
                return

        # If still overlapping after all iterations, grow canvas
        print(f"[Layout] {iteration + 1} overlap-fix iterations exhausted, "
              f"expanding canvas")
        self.def_.page_width = int(self.def_.page_width * 1.2)
        self.def_.page_height = int(self.def_.page_height * 1.2)

    def _nodes_overlap(self, n1: NodeDef, n2: NodeDef,
                        tolerance: int = 5) -> bool:
        """Check if two nodes overlap with configurable tolerance (px)."""
        return not (
            n1.x + n1.width + tolerance < n2.x or
            n2.x + n2.width + tolerance < n1.x or
            n1.y + n1.height + tolerance < n2.y or
            n2.y + n2.height + tolerance < n1.y
        )

    def _push_apart(self, n1: NodeDef, n2: NodeDef):
        """Push two overlapping nodes apart.

        After pushing, checks if pushed node overlaps a third node
        and continues pushing until clear (greedy approach).
        """
        dx = n2.x - n1.x
        dy = n2.y - n1.y

        min_gap_h = max(DEFAULT_ELEM_GAP_H, self.def_.spacing_h)
        min_gap_v = max(DEFAULT_ELEM_GAP_V, self.def_.spacing_v)

        if abs(dx) > abs(dy):
            if dx > 0:
                n2.x = n1.x + n1.width + min_gap_h
            else:
                n1.x = n2.x + n2.width + min_gap_h
        else:
            if dy > 0:
                n2.y = n1.y + n1.height + min_gap_v
            else:
                n1.y = n2.y + n2.height + min_gap_v

    def _align_to_grid(self):
        """Align all coordinates to grid."""
        grid_step = max(GRID_SIZE, self.def_.grid_size)
        for node in self.def_.nodes:
            node.x = round(node.x / grid_step) * grid_step
            node.y = round(node.y / grid_step) * grid_step
        for group in self.def_.groups:
            group.x = round(group.x / grid_step) * grid_step
            group.y = round(group.y / grid_step) * grid_step

    def _auto_resize_canvas(self):
        """Expand canvas to fit all laid-out nodes, groups, and notes."""
        if not self.def_.auto_size:
            return

        # Consider all elements: nodes, groups, and notes
        max_x = max((n.x + n.width for n in self.def_.nodes), default=0)
        max_y = max((n.y + n.height for n in self.def_.nodes), default=0)

        if self.def_.groups:
            max_x = max(max_x, max((g.x + g.width for g in self.def_.groups), default=0))
            max_y = max(max_y, max((g.y + g.height for g in self.def_.groups), default=0))

        for note in self.def_.notes:
            nx = note.get("_x", 0) + note.get("width", 180)
            ny = note.get("_y", 0) + note.get("height", 80)
            max_x = max(max_x, nx)
            max_y = max(max_y, ny)

        self.def_.page_width = max(self.def_.page_width, int(max_x + DEFAULT_CANVAS_MARGIN))
        self.def_.page_height = max(self.def_.page_height, int(max_y + DEFAULT_CANVAS_MARGIN))


def parse_input(input_path: str) -> DiagramDef:
    """Parse YAML or JSON input file.

    Only accepts 'create' action (or no action). Rejects 'patch' and 'scaffold'
    to prevent accidental full overwrites.
    """
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError:
        data = json.loads(content)

    action = data.get("action", "create")
    if action in ("scaffold",):
        raise ValueError(
            f"layout_generator.py does not support action='{action}'. "
            f"Use incremental_writer.py for scaffolding."
        )

    # Normalize patch format (add_nodes → nodes, add_edges → edges)
    if data.get('add_nodes'):
        data['nodes'] = data.pop('add_nodes')
    if data.get('add_edges'):
        data['edges'] = data.pop('add_edges')

    return _dict_to_diagram(data)


def _dict_to_diagram(data: Dict[str, Any]) -> DiagramDef:
    """Convert dict to DiagramDef."""
    def_ = DiagramDef()

    # Layout settings
    layout = data.get('layout', {})
    def_.layout_algorithm = layout.get('algorithm', 'layered')
    def_.layout_direction = layout.get('direction', 'top-to-bottom')
    def_.preserve_existing = layout.get('preserve_existing', False)
    page_settings = layout.get('page', {})
    def_.page_width = page_settings.get('width', DEFAULT_PAGE_WIDTH)
    def_.page_height = page_settings.get('height', DEFAULT_PAGE_HEIGHT)
    def_.spacing_h = layout.get('spacing', {}).get('horizontal', DEFAULT_ELEM_GAP_H)
    def_.spacing_v = layout.get('spacing', {}).get('vertical', DEFAULT_ELEM_GAP_V)
    def_.route_spacing = layout.get('route_spacing', DEFAULT_ROUTE_TRACK_SPACING)
    def_.edge_animation = layout.get('edge_animation', '')
    def_.grid_size = layout.get('grid_size', GRID_SIZE)
    def_.auto_size = layout.get('auto_size', True)

    # Groups
    for g in data.get('groups', []):
        name = g.get('name')
        if not name:
            print(f"Warning: Skipping group with missing 'name'", file=sys.stderr)
            continue
        label = g.get('label', name)
        def_.groups.append(GroupDef(
            name=name,
            label=label,
            group_type=g.get('type', 'service'),
            path=g.get('path', '')
        ))

    # Nodes
    for n_idx, n in enumerate(data.get('nodes', [])):
        node_id = n.get('id')
        node_label = n.get('label')
        if not node_id:
            print(f"Warning: Skipping node at index {n_idx} with missing 'id'", file=sys.stderr)
            continue
        if not node_label:
            print(f"Warning: Node '{node_id}' has no 'label', using id", file=sys.stderr)
            node_label = node_id
        lines = n.get('lines', [0, 0])
        if isinstance(lines, str):
            try:
                lines = [int(x) for x in lines.split(',')]
            except ValueError:
                print(f"Warning: Node '{node_id}' has invalid lines '{lines}'", file=sys.stderr)
                lines = [0, 0]
        scale = n.get('scale', 1.0)
        if not isinstance(scale, (int, float)) or scale <= 0:
            print(f"Warning: Node '{node_id}' has invalid scale '{scale}', using 1.0", file=sys.stderr)
            scale = 1.0
        def_.nodes.append(NodeDef(
            id=node_id,
            label=node_label,
            node_type=n.get('type', 'service'),
            group=n.get('group'),
            path=n.get('path', ''),
            lines=lines,
            description=n.get('description', ''),
            members=n.get('members', []),
            container=n.get('container', False),
            scale=scale,
        ))

    # Notes (decorative comment boxes with autosizeText)
    for note in data.get('notes', []):
        def_.notes.append(note)

    # Edges
    for e_idx, e in enumerate(data.get('edges', [])):
        source_id = e.get('from')
        target_id = e.get('to')
        if not source_id:
            print(f"Warning: Skipping edge at index {e_idx} with missing 'from'", file=sys.stderr)
            continue
        if not target_id:
            print(f"Warning: Skipping edge at index {e_idx} with missing 'to'", file=sys.stderr)
            continue
        lines = e.get('lines', [0, 0])
        if isinstance(lines, str):
            try:
                lines = [int(x) for x in lines.split(',')]
            except ValueError:
                print(f"Warning: Edge '{source_id}→{target_id}' has invalid lines", file=sys.stderr)
                lines = [0, 0]
        def_.edges.append(EdgeDef(
            source_id=source_id,
            target_id=target_id,
            label=e.get('label', ''),
            path=e.get('path', ''),
            lines=lines,
            style=e.get('style', 'solid'),
            animation=e.get('animation', '')
        ))

    return def_


def generate_xml(diagram_def: DiagramDef, existing_xml: Optional[str] = None) -> str:
    """Generate drawio XML from diagram definition."""
    # Build group map
    group_map: Dict[str, GroupDef] = {}
    for g in diagram_def.groups:
        group_map[g.name] = g

    # Build XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<mxfile host="app.diagrams.net" agent="drawio-architect" version="2.0.0" type="device">',
        f'  <diagram id="diagram-1" name="Architecture">',
        f'    <mxGraphModel dx="1422" dy="794" grid="1" gridSize="{GRID_SIZE}" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{diagram_def.page_width}" pageHeight="{diagram_def.page_height}" math="0" shadow="0">',
        '      <root>',
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    next_id = 2
    group_id_map: Dict[str, int] = {}
    node_id_map: Dict[str, int] = {}

    # Create groups (swimlanes)
    for group in diagram_def.groups:
        group_id = next_id
        group_id_map[group.name] = group_id
        next_id += 1

        colors = get_color_by_type(group.group_type)
        style = (f"swimlane;startSize=30;whiteSpace=wrap;html=1;"
                 f"fillColor={colors['fillColor']};strokeColor={colors['strokeColor']};"
                 f"fontSize=14;fontStyle=1;swimlaneLine=1;"
                 f"collapsible=1;expand=1")

        lines.append(f'        <object label="{escape_xml(group.label)}"')
        if group.path:
            p = _fix_hediet_path(group.path)
            lines.append(f'                hedietLinkedDataV1_path="{escape_xml(p)}"')
            lines.append(f'                hedietLinkedDataV1_start_line_x-num="0"')
            lines.append(f'                hedietLinkedDataV1_end_line_x-num="0"')
        lines.append(f'                id="{group_id}">')
        lines.append(f'          <mxCell style="{style}" vertex="1" parent="1">')
        lines.append(f'            <mxGeometry x="{group.x:.0f}" y="{group.y:.0f}" width="{group.width:.0f}" height="{group.height:.0f}" as="geometry" />')
        lines.append('          </mxCell>')
        lines.append('        </object>')

    # Create nodes
    for node in diagram_def.nodes:
        node_id = next_id
        node_id_map[node.id] = node_id
        next_id += 1

        colors = get_color_by_type(node.node_type)
        shape = SHAPE_MAP.get(node.node_type, 'rounded=1')

        parent_id = group_id_map.get(node.group, 1)

        # Calculate relative position if in group
        x = node.x
        y = node.y
        if node.group and node.group in group_map:
            group = group_map[node.group]
            x = node.x - group.x
            y = node.y - group.y

        if node.container and node.members:
            # Container: swimlane with stackLayout + autosizeText for fitting text
            style = (f"swimlane;fontStyle=1;childLayout=stackLayout;horizontal=1;"
                     f"startSize=30;horizontalStack=0;resizeParent=1;resizeParentMax=0;"
                     f"resizeLast=0;collapsible=1;marginBottom=0;whiteSpace=wrap;html=1;"
                     f"autosizeText=1;"
                     f"fillColor={colors['fillColor']};strokeColor={colors['strokeColor']}")

            lines.append(f'        <object label="{escape_xml(node.label)}"')
            if node.path:
                p = _fix_hediet_path(node.path)
                lines.append(f'                hedietLinkedDataV1_path="{escape_xml(p)}"')
                lines.append(f'                hedietLinkedDataV1_start_line_x-num="{node.lines[0]}"')
                lines.append(f'                hedietLinkedDataV1_end_line_x-num="{node.lines[1]}"')
            lines.append(f'                id="{node_id}">')
            lines.append(f'          <mxCell style="{style}" vertex="1" parent="{parent_id}">')
            lines.append(f'            <mxGeometry x="{x:.0f}" y="{y:.0f}" width="{node.width:.0f}" height="{node.height:.0f}" as="geometry" />')
            lines.append('          </mxCell>')
            lines.append('        </object>')

            # Child text cells (display only, no code link)
            for idx, member_label in enumerate(node.members):
                member_id = next_id
                next_id += 1
                member_top = 30 + idx * 22
                member_style = ("text;strokeColor=none;fillColor=none;align=left;"
                                "verticalAlign=middle;spacingLeft=4;spacingRight=4;"
                                "autosizeText=1;fontSize=10;"
                                "points=[[0,0.5],[1,0.5]];portConstraint=eastwest;"
                                "rotatable=0;whiteSpace=wrap;html=1;")
                lines.append(f'        <mxCell id="{member_id}"')
                lines.append(f'                style="{member_style}"')
                lines.append(f'                value="{escape_xml(member_label)}"')
                lines.append(f'                vertex="1" parent="{node_id}">')
                lines.append(f'          <mxGeometry y="{member_top}" width="{node.width:.0f}" height="22" as="geometry" />')
                lines.append('        </mxCell>')
        else:
            # Regular node with autosizeText so labels never overflow
            style_parts = [shape]
            style_parts.append(f"whiteSpace=wrap;html=1")
            style_parts.append(f"fillColor={colors['fillColor']}")
            style_parts.append(f"strokeColor={colors['strokeColor']}")
            style_parts.append("fontSize=12")
            style_parts.append("autosizeText=1")
            if node.node_type in ('entry', 'service', 'gateway'):
                style_parts.append("fontStyle=1")
            style = ";".join(style_parts)

            lines.append(f'        <object label="{escape_xml(node.label)}"')
            if node.path:
                p = _fix_hediet_path(node.path)
                lines.append(f'                hedietLinkedDataV1_path="{escape_xml(p)}"')
                lines.append(f'                hedietLinkedDataV1_start_line_x-num="{node.lines[0]}"')
                lines.append(f'                hedietLinkedDataV1_end_line_x-num="{node.lines[1]}"')
            lines.append(f'                id="{node_id}">')
            lines.append(f'          <mxCell style="{style}" vertex="1" parent="{parent_id}">')
            lines.append(f'            <mxGeometry x="{x:.0f}" y="{y:.0f}" width="{node.width:.0f}" height="{node.height:.0f}" as="geometry" />')
            lines.append('          </mxCell>')
            lines.append('        </object>')

    # Create notes (decorative comment boxes with autosizeText)
    for note in diagram_def.notes:
        note_id = next_id
        next_id += 1
        note_style = ("shape=note;whiteSpace=wrap;html=1;backgroundOutline=1;autosizeText=1;"
                      "fontColor=#000000;darkOpacity=0.05;fillColor=#FFF9B2;"
                      "strokeColor=none;fillStyle=solid;fontSize=14;direction=west;"
                      "gradientDirection=north;gradientColor=#FFF2A1;shadow=1;size=20;pointerEvents=1;")
        note_parent = group_id_map.get(note.get("group"), 1)
        # Use layout-computed positions from _position_notes()
        nx = note.get("_x", 50)
        ny = note.get("_y", 50)
        nw = note.get("width", 180)
        nh = note.get("height", 80)
        lines.append(f'        <mxCell id="{note_id}"')
        lines.append(f'                style="{note_style}"')
        lines.append(f'                value="{escape_xml(note.get("text", ""))}"')
        lines.append(f'                vertex="1" parent="{note_parent}">')
        lines.append(f'          <mxGeometry x="{nx}" y="{ny}" width="{nw}" height="{nh}" as="geometry" />')
        lines.append('        </mxCell>')

    # First pass: compute edge routes from node ports and create a raw route queue.
    source_edge_counts: Dict[str, int] = {}
    target_edge_counts: Dict[str, int] = {}
    for edge in diagram_def.edges:
        source_edge_counts[edge.source_id] = source_edge_counts.get(edge.source_id, 0) + 1
        target_edge_counts[edge.target_id] = target_edge_counts.get(edge.target_id, 0) + 1

    edge_routes = _build_edge_routes(diagram_def, source_edge_counts, target_edge_counts)
    _refine_edge_routes(edge_routes, diagram_def)

    for route in edge_routes:
        edge = route.edge
        edge_id = next_id
        next_id += 1

        source_id = node_id_map.get(edge.source_id, edge.source_id)
        target_id = node_id_map.get(edge.target_id, edge.target_id)

        style = "endArrow=classic;endFill=1;html=1;strokeColor=#666666;fontSize=10;edgeStyle=orthogonalEdgeStyle;elbow=vertical"
        if edge.style == "dashed":
            style += ";dashed=1"

        if edge.animation == 'flow' or (not edge.animation and diagram_def.edge_animation == 'flow'):
            style += ";animation=1"

        style += f";exitX={round(route.exit_x, 2)};exitY={round(route.exit_y, 2)};"
        style += f"entryX={round(route.entry_x, 2)};entryY={round(route.entry_y, 2)}"
        style += f";sourcePerimeterSpacing={route.source_perimeter_spacing};"
        style += f"targetPerimeterSpacing={route.target_perimeter_spacing}"

        lines.append(f'        <object label="{escape_xml(edge.label)}"')
        if edge.path:
            p = _fix_hediet_path(edge.path)
            lines.append(f'                hedietLinkedDataV1_path="{escape_xml(p)}"')
            lines.append(f'                hedietLinkedDataV1_start_line_x-num="{edge.lines[0]}"')
            lines.append(f'                hedietLinkedDataV1_end_line_x-num="{edge.lines[1]}"')
        lines.append(f'                id="{edge_id}">')
        lines.append(f'          <mxCell style="{style}" edge="1" parent="1" source="{source_id}" target="{target_id}">')

        if len(route.points) > 2:
            # Only bend points (exclude source and target perim points)
            bend_points = route.points[1:-1]
            lines.append('            <mxGeometry relative="1" as="geometry">')
            lines.append('              <Array as="points">')
            for p in bend_points:
                lines.append(f'                <mxPoint x="{p.x:.0f}" y="{p.y:.0f}" />')
            lines.append('              </Array>')
            lines.append('            </mxGeometry>')
        else:
            lines.append('            <mxGeometry relative="1" as="geometry" />')

        lines.append('          </mxCell>')
        lines.append('        </object>')

    lines.extend([
        '      </root>',
        '    </mxGraphModel>',
        '  </diagram>',
        '</mxfile>',
    ])

    return '\n'.join(lines)


def escape_xml(text: str) -> str:
    """Escape XML special characters."""
    return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))


def main():
    parser = argparse.ArgumentParser(description='Generate drawio XML with automatic layout')
    parser.add_argument('--input', '-i', help='Input YAML/JSON file')
    parser.add_argument('--output', '-o', required=True, help='Output .drawio file')
    parser.add_argument('--stdin', action='store_true', help='Read from stdin')
    args = parser.parse_args()

    if args.stdin:
        import sys
        content = sys.stdin.read()
        try:
            data = yaml.safe_load(content)
        except yaml.YAMLError:
            data = json.loads(content)
        action = data.get("action", "create")
        if action in ("patch", "scaffold"):
            print(f"Error: action='{action}' is not supported by layout_generator.py. "
                  f"Use incremental_reader.py for patches.", file=sys.stderr)
            sys.exit(1)
        diagram_def = _dict_to_diagram(data)
    elif args.input:
        diagram_def = parse_input(args.input)
    else:
        print("Error: Provide --input or --stdin", file=sys.stderr)
        sys.exit(1)

    # Compute layout
    engine = LayoutEngine(diagram_def)
    engine.compute_layout()

    # Generate XML
    xml = generate_xml(diagram_def)

    # Write output
    with open(args.output, 'w', encoding='utf-8') as f:
        f.write(xml)

    print(f"Generated: {args.output}")
    print(f"  Nodes: {len(diagram_def.nodes)}")
    print(f"  Edges: {len(diagram_def.edges)}")
    print(f"  Groups: {len(diagram_def.groups)}")
    print(f"  Layout: {diagram_def.layout_algorithm} ({diagram_def.layout_direction})")


if __name__ == '__main__':
    main()
