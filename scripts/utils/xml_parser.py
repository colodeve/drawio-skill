"""XML parsing utilities for drawio files."""

import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path


@dataclass
class NodeInfo:
    """Information about a drawio node/vertex."""
    id: str
    label: str
    x: float
    y: float
    width: float
    height: float
    style: str = ""
    parent: Optional[str] = None
    path: Optional[str] = None
    start_line: Optional[int] = None
    start_col: Optional[int] = None
    end_line: Optional[int] = None
    end_col: Optional[int] = None
    symbol: Optional[str] = None
    raw_attributes: Dict[str, Any] = field(default_factory=dict)

    def get_bounding_box(self) -> Tuple[float, float, float, float]:
        """Get bounding box as (x1, y1, x2, y2)."""
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def get_center(self) -> Tuple[float, float]:
        """Get center point as (cx, cy)."""
        return (self.x + self.width / 2, self.y + self.height / 2)


@dataclass
class EdgeInfo:
    """Information about a drawio edge/connection."""
    id: str
    source_id: str
    target_id: str
    style: str = ""
    label: str = ""
    source_port: Optional[str] = None
    target_port: Optional[str] = None
    path: Optional[str] = None
    start_line: Optional[int] = None
    end_line: Optional[int] = None


@dataclass
class DiagramData:
    """Complete diagram data structure."""
    nodes: List[NodeInfo] = field(default_factory=list)
    edges: List[EdgeInfo] = field(default_factory=list)
    page_width: int = 850
    page_height: int = 1100
    source_file: Optional[str] = None


class XmlParser:
    """Parser for drawio XML files."""

    MX_CELL = "{http://draw.io.mxgraph.org/mxgraph}mxCell"
    MX_GEOMETRY = "{http://draw.io.mxgraph.org/mxgraph}mxGeometry"
    OBJECT_TAG = "object"
    MX_CELL_TAG = "mxCell"
    MX_GRAPH_MODEL = "{http://draw.io.mxgraph.org/mxgraph}mxGraphModel"

    HEDIET_ATTRS = [
        "hedietLinkedDataV1_path",
        "hedietLinkedDataV1_start_line_x-num",
        "hedietLinkedDataV1_start_col_x-num",
        "hedietLinkedDataV1_end_line_x-num",
        "hedietLinkedDataV1_end_col_x-num",
        "hedietLinkedDataV1_symbol",
    ]

    def __init__(self, drawio_file: Optional[str] = None):
        self.drawio_file = drawio_file
        self.tree: Optional[ET.ElementTree] = None
        self.root: Optional[ET.Element] = None
        self.namespace = {"mx": "http://draw.io.mxgraph.org/mxgraph"}
        self._data: Optional[DiagramData] = None

        if drawio_file and os.path.exists(drawio_file):
            self.load(drawio_file)

    @property
    def nodes(self) -> List[NodeInfo]:
        return self._data.nodes if self._data else []

    @nodes.setter
    def nodes(self, value: List[NodeInfo]):
        if self._data:
            self._data.nodes = value

    def load(self, drawio_file: str) -> DiagramData:
        """Load and parse a drawio XML file."""
        self.drawio_file = drawio_file
        self.tree = ET.parse(drawio_file)
        self.root = self.tree.getroot()
        return self.parse()

    def load_from_string(self, xml_content: str) -> DiagramData:
        """Parse drawio XML from string content."""
        self.tree = ET.ElementTree(ET.fromstring(xml_content))
        self.root = self.tree.getroot()
        return self.parse()

    def _local_tag(self, tag_name: str) -> str:
        """Get local tag name (strip namespace)."""
        return tag_name.split("}")[-1] if "}" in tag_name else tag_name

    def _find_geom(self, cell: ET.Element) -> Optional[ET.Element]:
        """Find mxGeometry child, handling both namespaced and non-namespaced XML."""
        for child in cell.iter():
            local = self._local_tag(child.tag)
            if local == "mxGeometry":
                return child
        return None

    def parse(self) -> DiagramData:
        """Parse the loaded XML and extract diagram data."""
        data = DiagramData(source_file=self.drawio_file)
        self._data = data

        if self.root is None:
            return data

        self._extract_page_dimensions()
        data.page_width = self.page_width
        data.page_height = self.page_height

        cells = self._find_all_cells()
        for cell in cells:
            # draw.io uses edge="1" for edges, vertex="1" for vertices
            # For <object> elements, the edge attribute is on the inner mxCell
            is_edge = cell.get("edge") == "1"
            if not is_edge:
                inner = cell.find(".//mxCell")
                if inner is not None:
                    is_edge = inner.get("edge") == "1"
            if is_edge:
                edge = self._parse_edge(cell)
                if edge:
                    data.edges.append(edge)
            else:
                node = self._parse_vertex(cell)
                if node:
                    data.nodes.append(node)

        return data

    def _extract_page_dimensions(self) -> None:
        """Extract page dimensions from root element."""
        self.page_width = 850
        self.page_height = 1100

        if self.root is None:
            return
        # Try to find mxGraphModel element (may or may not have namespace)
        mgm = None
        for elem in self.root.iter():
            tag = elem.tag
            if isinstance(tag, str) and tag.endswith('mxGraphModel'):
                mgm = elem
                break

        if mgm is not None:
            page_width = mgm.get('pageWidth', mgm.get('pagewidth', '850'))
            page_height = mgm.get('pageHeight', mgm.get('pageheight', '1100'))
            try:
                self.page_width = int(page_width)
                self.page_height = int(page_height)
            except (ValueError, TypeError):
                pass
            return

        # Fallback: look under <diagram> for nested attributes
        diagram = self.root.find('.//diagram')
        if diagram is not None:
            etree_node = diagram.find('.//*')
            if etree_node is not None:
                page_width = etree_node.get("pageWidth", "850")
                page_height = etree_node.get("pageHeight", "1100")
                try:
                    self.page_width = int(page_width)
                    self.page_height = int(page_height)
                except ValueError:
                    pass

    def _find_all_cells(self) -> List[ET.Element]:
        """Find all cell elements (mxCell and object tags).
        Skips mxCell elements that are wrapped inside <object> tags
        (they are handled via their parent <object>)."""
        # Build parent map once for efficiency
        parent_map = {}
        if self.root is not None:
            for parent in self.root.iter():
                for child in parent:
                    parent_map[id(child)] = parent

        cells = []
        for elem in self.root.iter() if self.root else []:
            tag_name = self._local_tag(elem.tag)
            if tag_name not in ("mxCell", "object"):
                continue
            cell_id = elem.get("id")
            if cell_id in ("0", "1"):
                continue
            # Skip mxCells that are inside <object> (they're handled via the object)
            if tag_name == "mxCell":
                par = parent_map.get(id(elem))
                if par is not None and self._local_tag(par.tag) == "object":
                    continue
            cells.append(elem)
        return cells

    def _parse_vertex(self, cell: ET.Element) -> Optional[NodeInfo]:
        """Parse a vertex/cell element."""
        cell_id = cell.get("id")
        if not cell_id:
            return None

        # Look for mxGeometry in all descendants (handles nested structure & namespaces)
        geometry = self._find_geom(cell)
        if geometry is None:
            x, y, w, h = 0, 0, 100, 60
        else:
            x = self._parse_float(geometry.get("x", "0"))
            y = self._parse_float(geometry.get("y", "0"))
            w = self._parse_float(geometry.get("width", "100"))
            h = self._parse_float(geometry.get("height", "60"))

        # Get label from object tag or mxCell value
        label = cell.get("label", "") or cell.get("value", "")
        if label:
            label = self._clean_html(label)

        # Get style from inner mxCell (for object) or directly from cell (for bare mxCell)
        local = self._local_tag(cell.tag)
        if local == "object":
            style_cell = cell.find(".//mxCell") or cell
        else:
            style_cell = cell
        style = style_cell.get("style", "")
        path = None
        start_line = None
        end_line = None

        for attr in self.HEDIET_ATTRS:
            value = cell.get(attr)
            if value:
                if attr == "hedietLinkedDataV1_path":
                    path = value
                elif attr == "hedietLinkedDataV1_start_line_x-num":
                    try:
                        start_line = int(value)
                    except ValueError:
                        pass
                elif attr == "hedietLinkedDataV1_end_line_x-num":
                    try:
                        end_line = int(value)
                    except ValueError:
                        pass

        return NodeInfo(
            id=cell_id,
            label=label,
            x=x,
            y=y,
            width=w,
            height=h,
            style=style,
            parent=cell.get("parent"),
            path=path,
            start_line=start_line,
            start_col=None,
            end_line=end_line,
            end_col=None,
            symbol=None,
            raw_attributes={}
        )

    def _parse_edge(self, cell: ET.Element) -> Optional[EdgeInfo]:
        """Parse an edge element."""
        cell_id = cell.get("id")
        if not cell_id:
            return None

        # For <object> wrappers, source/target are on the inner <mxCell>
        mxcell = cell
        local = self._local_tag(cell.tag)
        if local == "object":
            mxcell = cell.find(".//mxCell")
            if mxcell is None:
                return None

        source = mxcell.get("source")
        target = mxcell.get("target")
        if not source or not target:
            return None

        style = mxcell.get("style", "")
        label = cell.get("value", "") or cell.get("label", "")
        if label:
            label = self._clean_html(label)

        path = None
        start_line = None
        end_line = None

        for attr in self.HEDIET_ATTRS:
            value = cell.get(attr)
            if value:
                if attr == "hedietLinkedDataV1_path":
                    path = value
                elif attr == "hedietLinkedDataV1_start_line_x-num":
                    try:
                        start_line = int(value)
                    except ValueError:
                        pass
                elif attr == "hedietLinkedDataV1_end_line_x-num":
                    try:
                        end_line = int(value)
                    except ValueError:
                        pass

        return EdgeInfo(
            id=cell_id,
            source_id=source,
            target_id=target,
            style=style,
            label=label,
            source_port=cell.get("sourcePort"),
            target_port=cell.get("targetPort"),
            path=path,
            start_line=start_line,
            end_line=end_line
        )

    def _clean_html(self, text: str) -> str:
        """Remove HTML tags and decode entities."""
        import html
        import re

        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        return text.strip()

    def _parse_float(self, value: str) -> float:
        """Safely parse a float value."""
        try:
            return float(value)
        except ValueError:
            return 0.0

    def get_nodes_with_invalid_paths(self, base_dir: Optional[str] = None) -> List[Tuple[NodeInfo, str]]:
        """Get nodes with invalid hedietLinkedDataV1_path values."""
        invalid = []
        if base_dir is None and self.drawio_file:
            base_dir = os.path.dirname(os.path.abspath(self.drawio_file))

        for node in self.nodes:
            if node.path:
                full_path = os.path.join(base_dir, node.path) if base_dir else node.path
                if not os.path.exists(full_path):
                    invalid.append((node, node.path))

        return invalid

    def get_nodes_missing_line_info(self) -> List[NodeInfo]:
        """Get nodes that have paths but missing line numbers."""
        return [n for n in self.nodes if n.path and (n.start_line is None or n.end_line is None)]

    def extract_all_paths(self) -> List[Dict[str, Any]]:
        """Extract all hedietLinkedDataV1 paths from the diagram."""
        paths = []
        for node in self.nodes:
            if node.path:
                paths.append({
                    "node_id": node.id,
                    "label": node.label,
                    "path": node.path,
                    "start_line": node.start_line,
                    "end_line": node.end_line,
                    "x": node.x,
                    "y": node.y
                })
        return paths

    def save(self, output_file: str, data: DiagramData):
        """Save the diagram data back to a drawio file — preserves original XML structure.

        Only updates geometry and labels in-place; does NOT reformat/re-pretty-print.
        """
        if self.tree is None or self.root is None:
            raise ValueError("No loaded diagram to save")

        node_map = {node.id: node for node in data.nodes}

        cells = self._find_all_cells()
        for cell in cells:
            cell_id = cell.get("id")
            if cell_id not in node_map:
                continue
            node = node_map[cell_id]
            geometry = self._find_geom(cell)
            if geometry is not None:
                geometry.set("x", str(node.x))
                geometry.set("y", str(node.y))
                geometry.set("width", str(node.width))
                geometry.set("height", str(node.height))
            if node.label:
                # For bare mxCell: value attribute stores label
                local = self._local_tag(cell.tag)
                if local == "mxCell":
                    cell.set("value", node.label)
                else:
                    cell.set("label", node.label)
                    mx_cell = cell.find(".//mxCell")
                    if mx_cell is not None:
                        mx_cell.set("value", node.label)

        # Write directly — preserves original whitespace and attribute order
        xml_bytes = ET.tostring(self.root, encoding='utf-8', method='xml', xml_declaration=True)
        with open(output_file, 'wb') as f:
            f.write(xml_bytes)


def parse_drawio_file(file_path: str) -> DiagramData:
    """Convenience function to parse a drawio file."""
    parser = XmlParser(file_path)
    return parser.parse()


def _update_cell_geometry(cell: ET.Element, x: float, y: float, width: float, height: float):
    """Update the geometry of a cell element."""
    # Search all descendants for mxGeometry (handles namespaced XML)
    geometry = None
    for child in cell.iter():
        local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
        if local == "mxGeometry":
            geometry = child
            break
    if geometry is None:
        geometry = ET.SubElement(cell, "mxGeometry")
    
    geometry.set("x", str(x))
    geometry.set("y", str(y))
    geometry.set("width", str(width))
    geometry.set("height", str(height))
    geometry.set("as", "geometry")


def get_line_count(file_path: str) -> int:
    """Get the number of lines in a file."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return sum(1 for _ in f)
    except (OSError, IOError):
        return 0
