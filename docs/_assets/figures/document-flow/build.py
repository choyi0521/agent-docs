#!/usr/bin/env python3
"""Build the document-flow figure from its ordered declarative source.

Rebuild from the repository root with:
    python -B docs/_assets/figures/document-flow/build.py

The standard library is the only dependency.  Element and attribute order are
stable, so identical source bytes produce identical canonical artifacts.
"""

from __future__ import annotations

from html import escape
import json
from pathlib import Path
import re
from typing import Any


BUNDLE = Path(__file__).resolve().parent
SOURCE = BUNDLE / "figure.source.json"
SVG_OUTPUT = BUNDLE / "figure.svg"
HTML_OUTPUT = BUNDLE / "figure.html"

ALLOWED_ELEMENTS = frozenset(
    {
        "circle",
        "desc",
        "ellipse",
        "g",
        "line",
        "path",
        "polygon",
        "polyline",
        "rect",
        "svg",
        "text",
        "title",
        "tspan",
    }
)
ALLOWED_ATTRIBUTES = frozenset(
    {
        "aria-describedby",
        "aria-label",
        "aria-labelledby",
        "cx",
        "cy",
        "d",
        "dominant-baseline",
        "fill",
        "fill-opacity",
        "focusable",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "height",
        "id",
        "letter-spacing",
        "opacity",
        "points",
        "preserveAspectRatio",
        "r",
        "role",
        "rx",
        "ry",
        "stroke",
        "stroke-dasharray",
        "stroke-dashoffset",
        "stroke-linecap",
        "stroke-linejoin",
        "stroke-opacity",
        "stroke-width",
        "text-anchor",
        "transform",
        "vector-effect",
        "viewBox",
        "width",
        "x",
        "x1",
        "x2",
        "y",
        "y1",
        "y2",
    }
)
ID_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
URL_LIKE = re.compile(r"(?:url\s*\(|://|^//|javascript:|data:)", re.IGNORECASE)


def load_source() -> dict[str, Any]:
    value = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("figure.source.json must contain an object")
    return value


def validate_node(node: dict[str, Any], ids: set[str]) -> None:
    tag = node.get("tag")
    if tag not in ALLOWED_ELEMENTS or tag == "svg":
        raise ValueError(f"unsupported source element: {tag!r}")
    attributes = node.get("attrs", {})
    if not isinstance(attributes, dict):
        raise ValueError(f"{tag} attrs must be an object")
    for name, raw_value in attributes.items():
        if name not in ALLOWED_ATTRIBUTES:
            raise ValueError(f"unsupported source attribute: {name!r}")
        value = str(raw_value)
        if URL_LIKE.search(value):
            raise ValueError(f"URL-like attribute value is forbidden: {name!r}")
        if name == "id":
            if not ID_PATTERN.fullmatch(value) or value in ids:
                raise ValueError(f"invalid or duplicate id: {value!r}")
            ids.add(value)
    text = node.get("text")
    children = node.get("children", [])
    if text is not None and children:
        raise ValueError(f"{tag} cannot contain both text and children")
    if text is not None and tag not in {"title", "desc", "text", "tspan"}:
        raise ValueError(f"{tag} cannot contain text")
    if not isinstance(children, list):
        raise ValueError(f"{tag} children must be an array")
    for child in children:
        if not isinstance(child, dict):
            raise ValueError(f"{tag} child must be an object")
        validate_node(child, ids)


def render_node(node: dict[str, Any], depth: int) -> list[str]:
    indent = "  " * depth
    tag = node["tag"]
    attributes = node.get("attrs", {})
    serialized = "".join(
        f' {name}="{escape(str(attributes[name]), quote=True)}"'
        for name in sorted(attributes)
    )
    text = node.get("text")
    children = node.get("children", [])
    if text is not None:
        return [f"{indent}<{tag}{serialized}>{escape(str(text))}</{tag}>"]
    if not children:
        return [f"{indent}<{tag}{serialized} />"]
    result = [f"{indent}<{tag}{serialized}>"]
    for child in children:
        result.extend(render_node(child, depth + 1))
    result.append(f"{indent}</{tag}>")
    return result


def build_svg(source: dict[str, Any]) -> str:
    width = source.get("width")
    height = source.get("height")
    if not isinstance(width, int) or not isinstance(height, int) or width <= 0 or height <= 0:
        raise ValueError("width and height must be positive integers")
    title = source.get("title")
    description = source.get("description")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title must be a non-empty string")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("description must be a non-empty string")
    elements = source.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("elements must be a non-empty array")

    title_id = "document-flow-title"
    description_id = "document-flow-description"
    ids = {"document-flow-figure", title_id, description_id}
    nodes: list[dict[str, Any]] = [
        {"tag": "title", "attrs": {"id": title_id}, "text": title},
        {"tag": "desc", "attrs": {"id": description_id}, "text": description},
        *elements,
    ]
    for node in elements:
        if not isinstance(node, dict):
            raise ValueError("each element must be an object")
        validate_node(node, ids)

    root_attributes = {
        "aria-labelledby": f"{title_id} {description_id}",
        "focusable": "false",
        "height": str(height),
        "id": "document-flow-figure",
        "preserveAspectRatio": "xMidYMid meet",
        "role": "img",
        "viewBox": f"0 0 {width} {height}",
        "width": str(width),
    }
    attributes = "".join(
        f' {name}="{escape(value, quote=True)}"'
        for name, value in sorted(root_attributes.items())
    )
    lines = [
        f'<svg xmlns="http://www.w3.org/2000/svg"{attributes}>',
        *[line for node in nodes for line in render_node(node, 1)],
        "</svg>",
    ]
    return "\n".join(lines) + "\n"


def build_html(source: dict[str, Any]) -> str:
    caption = source.get("caption")
    if not isinstance(caption, str) or not caption.strip():
        raise ValueError("caption must be a non-empty string")
    description = str(source["description"])
    width = int(source["width"])
    height = int(source["height"])
    return (
        "<figure>\n"
        f'  <img src="figure.svg" width="{width}" height="{height}" '
        f'alt="{escape(description, quote=True)}">\n'
        f"  <figcaption>{escape(caption)}</figcaption>\n"
        "</figure>\n"
    )


def main() -> None:
    source = load_source()
    SVG_OUTPUT.write_text(build_svg(source), encoding="utf-8", newline="\n")
    HTML_OUTPUT.write_text(build_html(source), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
