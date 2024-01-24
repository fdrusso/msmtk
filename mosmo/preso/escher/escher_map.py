"""Render an Escher map as SVG."""
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Mapping, Optional, Tuple, Union

from IPython.display import display, SVG
from ipywidgets import Output

# Default Escher styles
CSS = """
    #canvas {
      fill: #ffffff;
      stroke: #cccccc;
    }
    .label {
      font-family: sans-serif;
      font-style: italic;
      font-weight: bold;
      stroke: none;
      text-rendering: optimizelegibility;
    }
    #reactions .label {
      font-size: 30px;
      fill: #334e75;
    }
    #reactions .label.stoich {
      font-size: 12px;
      fill: #334e75;
    }
    #metabolites .label {
      font-size: 20px;
      fill: black;
    }
"""
MET_FILL = "#e0865b"
MET_STROKE = "#a24510"
RXN_STROKE = "#334e75"


@dataclass
class Color:
    """Supports simple arithmetic on #rrggbb hex color strings."""
    r: float
    g: float
    b: float

    @staticmethod
    def from_hex(hexstr: str):
        if hexstr.startswith("#") and len(hexstr) == 7:
            return Color(int(hexstr[1:3], 16), int(hexstr[3:5], 16), int(hexstr[5:], 16))
        else:
            raise ValueError("Hex color string of style '#rrggbb' required")

    def __str__(self):
        return f"#{int(self.r + 0.5):02x}{int(self.g + 0.5):02x}{int(self.b + 0.5):02x}"

    def __add__(self, color: "Color"):
        return Color(self.r + color.r, self.g + color.g, self.b + color.b)

    def __sub__(self, color: "Color"):
        return Color(self.r - color.r, self.g - color.g, self.b - color.b)

    def __mul__(self, factor):
        return Color(self.r * factor, self.g * factor, self.b * factor)

    def __rmul__(self, factor):
        return self * factor

    def __truediv__(self, factor):
        return Color(self.r / factor, self.g / factor, self.b / factor)


class Scale:
    """Styler modeled after the Escher API metabolite and reaction scales.

    Color and/or size is scaled over one or more ranges, defined by "stops". Any value between two stops is styled by
    interpolating between the styles defined at those stops. Values outside the defined range are pegged at the minimum
    or maximum as appropriate.
    """

    def __init__(self, stops: Mapping[float, Tuple[str, float]], use_abs: bool = False):
        """Initialize a ScaleStyler.

        Args:
            stops: maps value -> (color, size). Either color or size may be None, but this choice should be consistent
                for all stops. At least 2 stops must be provided.
            use_abs: if True, styles are applied symmetrically around zero (i.e. based on the absolute value of the
                data). Default is False.

        Returns:
            A (color, style) tuple, where either color or style may be None.
        """
        self.stops = sorted(
            ((value, Color.from_hex(color), size) for value, (color, size) in stops.items()),
            key=lambda x: x[0]
        )
        self.use_abs = use_abs

    def style(self, value: float) -> Tuple[Color, float]:
        """Maps a value to an interpolated color and/or size."""
        if self.use_abs:
            value = abs(value)

        # Range check
        if value < self.stops[0][0]:
            return self.stops[0][1], self.stops[0][2]
        elif value > self.stops[-1][0]:
            return self.stops[-1][1], self.stops[-1][2]

        # In range: bracket the value
        lb = self.stops[0]
        for ub in self.stops[1:]:
            if ub[0] >= value:
                break
            lb = ub

        p = (value - lb[0]) / (ub[0] - lb[0])
        if lb[1] and ub[1]:
            color = p * ub[1] + (1 - p) * lb[1]
        else:
            color = None
        if lb[2] and ub[2]:
            size = p * ub[2] + (1 - p) * lb[2]
        else:
            size = None

        return color, size


def GaBuGeRd(minval=0, mid1=0.01, mid2=20, maxval=100):
    """Scale modeled after the GaBuGeRd scale preset of the Escher API."""
    return Scale({minval: ("#c8c8c8", 12), mid1: ("#9696ff", 16), mid2: ("#209123", 20), maxval: ("#ff0000", 25)},
                 use_abs=True)


def GaBuRd(minval=0, midval=20, maxval=100):
    """Scale modeled after the GaBuRd scale preset of the Escher API."""
    return Scale({minval: ("#c8c8c8", 12), midval: ("#9696ff", 20), maxval: ("#ff0000", 25)}, use_abs=True)


def RdYlBu(minval=0, midval=20, maxval=100):
    """Scale modeled after the RdYlBu scale preset of the Escher API."""
    return Scale({minval: ("#d7191c", 12), midval: ("#ffffbf", 20), maxval: ("#2c7bb6", 25)}, use_abs=True)


def GeGaRd(minval=-100, maxval=100):
    """Scale modeled after the GeGaRd scale preset of the Escher API."""
    return Scale({minval: ("#209123", 25), 0: ("#c8c8c8", 12), maxval: ("#ff0000", 25)}, use_abs=False)


def WhYlRd(minval=0, med=20, maxval=100):
    """Scale modeled after the WhYlRd scale preset of the Escher API."""
    return Scale({minval: ("#fffaf0", 20), med: ("#f1c470", 30), maxval: ("#800000", 40)}, use_abs=True)


def GaBu(minval=0, maxval=100):
    """A simple aesthetic light-gray to blue scale."""
    return Scale({minval: ("#eeeeee", 5), maxval: ("#1f77b4", 20)}, use_abs=True)


class EscherMap:
    """Renders a map file produced by the Escher pathway tool, http://escher.github.io/.

    Usage:
        diagram1 = EscherMap(json.loads(<mapfile>)))
        diagram1.draw(width="20cm")

        diagram2 = EscherMap(json.loads(<mapfile>)), reaction_scale=GaBuRd(midval=1.5, maxval=10))
        diagram2.draw(width="800px", reaction_data=<data>)

    The draw() method renders the pathway to an
    [Output](https://ipywidgets.readthedocs.io/en/stable/examples/Output%20Widget.html) widget, which displays
    automatically in a jupyter notebook, or can be composed with other widgets as needed.

    For greater control, use to_svg(), which returns a standard SVG document as an ET.Element. Users with web
    development or CSS experience can manipulate this to fine-tune its appearance. This can be rendered to a string, or
    saved to a file to be loaded into a drawing application such as Inkscape or Illustrator.
    """

    def __init__(self,
                 map_json,
                 width: Optional[Union[str, float, int]] = None,
                 height: Optional[Union[str, float, int]] = None,
                 reaction_scale: Optional[Scale] = None,
                 metabolite_scale: Optional[Scale] = None):
        self.width = width
        self.height = height
        self.reaction_scale = reaction_scale
        self.metabolite_scale = metabolite_scale

        self.origin = (map_json[1]["canvas"]["x"], map_json[1]["canvas"]["y"])
        self.size = (map_json[1]["canvas"]["width"], map_json[1]["canvas"]["height"])

        # All nodes may be referred to by some reaction segment. Only metabolite nodes will be rendered.
        all_nodes = {}
        self.metabolites = []
        for node_id, node in map_json[1]["nodes"].items():
            if node["node_type"] == "metabolite":
                metabolite = MapMetabolite(self, node)
                all_nodes[node_id] = metabolite
                self.metabolites.append(metabolite)
            else:
                all_nodes[node_id] = MapNode(self, node)

        self.reactions = []
        for reaction_id, reaction_json in map_json[1]["reactions"].items():
            self.reactions.append(MapReaction(self, reaction_json, all_nodes))

        self._widget = None

    def to_svg(
            self,
            metabolite_data: Optional[Mapping[str, float]] = None,
            reaction_data: Optional[Mapping[str, float]] = None,
            reaction_direction: Optional[Mapping[str, float]] = None) -> ET.Element:

        svg = ET.Element("svg",
                         {"width": str(self.width),
                          "height": str(self.height),
                          "viewBox": f"{self.origin[0]} {self.origin[1]} {self.size[0]} {self.size[1]}"}
                         )
        defs = ET.Element("defs")
        svg.append(defs)

        style = ET.Element("style", {"type": "text/css"})
        style.text = CSS
        defs.append(style)

        marker = ET.Element("marker", {"id": "arrowhead", "viewBox": "0 -10 13 20", "refX": "2", "refY": "0",
                                       "markerUnits": "strokeWidth", "markerWidth": "2", "markerHeight": "2",
                                       "orient": "auto"})
        marker.append(ET.Element("path", {"d": "M 0 -10 L 13 0 L 0 10 Z", "fill": "#334e75", "stroke": "none"}))
        defs.append(marker)

        root = ET.Element("g", {"id": "eschermap"})
        svg.append(root)

        # Background canvas
        root.append(
            ET.Element("rect",
                       {"id": "canvas",
                        "x": str(self.origin[0]),
                        "y": str(self.origin[1]),
                        "width": str(self.size[0]),
                        "height": str(self.size[1])}
                       ))

        # Reactions with segments and labels, possibly styled according to data values
        reactions = ET.Element("g", {"id": "reactions", "fill": "none", "stroke": RXN_STROKE, "stroke-width": "10"})
        if reaction_data:
            # Change the default to de-emphasize elements with missing data
            reactions.set("stroke", "#eeeeee")
            reactions.set("stroke-width", "5")
        root.append(reactions)

        if reaction_data is None:
            reaction_data = {}
        if reaction_direction is None:
            reaction_direction = reaction_data
        for reaction in self.reactions:
            value = reaction_data.get(reaction.reaction_id)
            direction = reaction_direction.get(reaction.reaction_id)
            reactions.append(reaction.to_svg(value, direction))

        # Metabolite nodes, possibly styled according to data values
        metabolites = ET.Element("g",
                                 {"id": "metabolites", "fill": MET_FILL, "stroke": MET_STROKE, "stroke-width": "2"})
        if metabolite_data:
            # Change the default to de-emphasize elements with missing data
            metabolites.set("fill", "#eeeeee")
            metabolites.set("stroke", "none")
        root.append(metabolites)

        if metabolite_data is None:
            metabolite_data = {}
        for metabolite in self.metabolites:
            value = metabolite_data.get(metabolite.metabolite_id)
            metabolites.append(metabolite.to_svg(value))

        return svg

    @property
    def widget(self) -> Output:
        if self._widget is None:
            self._widget = Output()
        return self._widget

    def draw(self,
             metabolite_data: Optional[Mapping[str, float]] = None,
             reaction_data: Optional[Mapping[str, float]] = None,
             reaction_direction: Optional[Mapping[str, float]] = None) -> Output:
        self.widget.clear_output(wait=True)
        with self.widget:
            svg = self.to_svg(
                metabolite_data=metabolite_data,
                reaction_data=reaction_data,
                reaction_direction=reaction_direction)
            display(SVG(ET.tostring(svg, encoding="unicode")))
        return self.widget


class MapNode:
    """Any node that can serve as an endpoint for a segment."""

    def __init__(self, parent: EscherMap, node_json):
        self.parent = parent
        self.center = (node_json["x"], node_json["y"])


class MapMetabolite(MapNode):
    """A node that designates a metabolite."""

    def __init__(self, parent: EscherMap, node_json):
        super().__init__(parent, node_json)
        self.metabolite_id = node_json["bigg_id"]
        self.primary = node_json["node_is_primary"]
        self.label_pos = (node_json["label_x"], node_json["label_y"])

    def size(self) -> float:
        if self.primary:
            return 20.
        else:
            return 12.

    def to_svg(self, value=None) -> ET.Element:
        circle = ET.Element("circle", {"cx": str(self.center[0]), "cy": str(self.center[1]), "r": str(self.size())})
        if value is not None and self.parent.metabolite_scale is not None:
            # Override fill, stroke, and radius
            color, size = self.parent.metabolite_scale.style(value)
            circle.set("fill", str(color))
            circle.set("stroke", "none")
            circle.set("r", str(size))

        label = ET.Element("text", {"class": "label", "x": str(self.label_pos[0]), "y": str(self.label_pos[1])})
        label.text = self.metabolite_id

        group = ET.Element("g", {"name": self.metabolite_id})
        group.append(circle)
        group.append(label)
        return group


class MapReaction:
    """A collection of segments associating metabolites with a reaction."""

    def __init__(self, parent: EscherMap, reaction_json, all_nodes: Mapping[str, MapNode]):
        self.parent = parent
        self.reaction_id = reaction_json["bigg_id"]
        self.stoich = {m["bigg_id"]: m["coefficient"] for m in reaction_json["metabolites"]}
        self.reversible = reaction_json["reversibility"]
        self.label_pos = (reaction_json["label_x"], reaction_json["label_y"])

        self.segments = [MapSegment(self, segment_json, all_nodes) for segment_json in
                         reaction_json["segments"].values()]

    def to_svg(self, value=None, direction=None) -> ET.Element:
        color, size = None, None  # Inherit defaults
        if value is not None and self.parent.reaction_scale is not None:
            color, size = self.parent.reaction_scale.style(value)

        group = ET.Element("g", {"name": self.reaction_id})
        for segment in self.segments:
            arc = segment.to_svg()
            # Override stroke, width, and arrowheads to indicate reaction flux
            if color is not None:
                arc.set("stroke", str(color))
            if size is not None:
                arc.set("stroke-width", str(size))
            if direction is not None and segment.count is not None:
                if segment.count * direction > 0:
                    arc.set("marker-end", "url(#arrowhead)")
                else:
                    arc.set("marker-end", "")
            group.append(arc)

        label = ET.Element("text", {"class": "label", "x": str(self.label_pos[0]), "y": str(self.label_pos[1])})
        label.text = self.reaction_id
        group.append(label)
        return group


class MapSegment:
    """A single connection tying a metabolite to a reaction, or nodes within a reaction."""

    def __init__(self, reaction: MapReaction, segment_json, all_nodes: Mapping[str, MapNode]):
        self.reaction = reaction
        self.from_node = all_nodes[segment_json["from_node_id"]]
        self.to_node = all_nodes[segment_json["to_node_id"]]
        self.b1 = (segment_json["b1"]["x"], segment_json["b1"]["y"]) if segment_json["b1"] else None
        self.b2 = (segment_json["b2"]["x"], segment_json["b2"]["y"]) if segment_json["b2"] else None

        # Some maps swap whether a metabolite node is "from" or "to". Swap if necessary, to standardize on "to".
        if isinstance(self.from_node, MapMetabolite):
            self.from_node, self.to_node = self.to_node, self.from_node
            self.b1, self.b2 = self.b2, self.b1

        # Additional data for metabolite segments
        if isinstance(self.to_node, MapMetabolite):
            self.metabolite_id = self.to_node.metabolite_id
            self.count = reaction.stoich[self.metabolite_id]
            self.has_arrow = self.count > 0 or reaction.reversible
        else:
            self.metabolite_id = None
            self.count = None
            self.has_arrow = False

    def to_svg(self) -> ET.Element:
        start = self.from_node.center
        end = self.to_node.center

        if self.metabolite_id is None:
            # Just a connector between "midmarker" and "multimarker". Uae a <path> so css finds it.
            return ET.Element("path", {"d": f"M {start[0]:.1f} {start[1]:.1f} L {end[0]:.1f} {end[1]:.1f}"})
        # else...

        # Adjust the endpoint to approach the metabolite node but stop at a padded distance from it.
        approach = self.b2 or start  # tolerate missing b2
        dx = end[0] - approach[0]
        dy = end[1] - approach[1]
        l = math.sqrt(dx * dx + dy * dy)

        # Some fine-tuning to try to match escher's existing behavior.
        padding = 20. if self.has_arrow else 10.
        minlen = 5.
        _l = l - self.to_node.size() - padding
        if _l < minlen:
            _l = l - self.to_node.size()
        ratio = _l / l
        end = (approach[0] + dx * ratio, approach[1] + dy * ratio)

        if self.b1 and self.b2:
            path_attrs = {"d": f"M {start[0]:.1f} {start[1]:.1f} C {self.b1[0]:.1f} {self.b1[1]:.1f}" +
                               f" {self.b2[0]:.1f} {self.b2[1]:.1f} {end[0]:.1f} {end[1]:.1f}"}
        else:
            path_attrs = {"d": f"M {start[0]:.1f} {start[1]:.1f} L {end[0]:.1f} {end[1]:.1f}"}
        if self.has_arrow:
            path_attrs["marker-end"] = "url(#arrowhead)"
        path = ET.Element("path", path_attrs)

        count = abs(self.count)
        if count == 1:
            return path
        else:
            group = ET.Element("g")
            group.append(path)

            label_x = end[0] + dy / l * 24
            label_y = end[1] - dx / l * 24
            stoich_label = ET.Element("text", {"class": "label stoich", "x": str(label_x), "y": str(label_y)})
            stoich_label.text = str(count)
            group.append(stoich_label)
            return group
