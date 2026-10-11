#!/usr/bin/env python3
"""Audit a hand-built SVG schematic against final-size journal rules.

Checks, using only the standard library:

* effective text size at final physical size (font-size, ``scale``/``matrix``
  transforms, and the ``viewBox`` to ``width`` scale) against a floor and ceiling;
* canvas width against a journal maximum;
* text anchored outside the canvas;
* constructs that do not survive production: scripts, ``foreignObject``,
  gradients, filters, and external references.

It does not detect overlaps between boxes, crossing arrows, or outlined text, so
it never replaces looking at the rendered figure at final size.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from xml.etree import ElementTree as ET  # nosec B405 - DTDs and entities are rejected before parsing

PT_PER_UNIT = {"pt": 1.0, "px": 0.75, "mm": 72 / 25.4, "cm": 72 / 2.54, "in": 72.0, "": None}
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
LENGTH = re.compile(rf"^\s*({NUMBER})\s*(pt|px|mm|cm|in)?\s*$")
FUNCTION = re.compile(rf"(scale|matrix)\(([^)]*)\)")
FORBIDDEN = {
    "script": "FAIL",
    "foreignObject": "FAIL",
    "linearGradient": "WARN",
    "radialGradient": "WARN",
    "filter": "WARN",
}
MM_SINGLE, MM_DOUBLE = 89.0, 183.0


@dataclass(frozen=True)
class Finding:
    severity: str
    kind: str
    message: str


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_length(value: str | None) -> tuple[float, str] | None:
    match = LENGTH.match(value or "")
    return (float(match.group(1)), match.group(2) or "") if match else None


def style_value(element: ET.Element, name: str) -> str | None:
    style = element.get("style") or ""
    for part in style.split(";"):
        key, _, value = part.partition(":")
        if key.strip() == name:
            return value.strip()
    return element.get(name)


def transform_scale(element: ET.Element) -> float:
    """Isotropic scale contributed by this element's own ``transform``."""
    scale = 1.0
    for kind, args in FUNCTION.findall(element.get("transform") or ""):
        numbers = [float(n) for n in re.findall(NUMBER, args)]
        if kind == "scale" and numbers:
            sx = numbers[0]
            sy = numbers[1] if len(numbers) > 1 else sx
            scale *= abs(sx * sy) ** 0.5
        elif kind == "matrix" and len(numbers) >= 4:
            scale *= abs(numbers[0] * numbers[3] - numbers[1] * numbers[2]) ** 0.5
    return scale


def canvas_scale(root: ET.Element) -> tuple[float, float | None, bool]:
    """Return (points per user unit, width in pt or None, units_known)."""
    view_box = [float(n) for n in re.findall(NUMBER, root.get("viewBox") or "")]
    width = parse_length(root.get("width"))
    view_width = view_box[2] if len(view_box) == 4 and view_box[2] > 0 else None
    if width and PT_PER_UNIT.get(width[1]):
        width_pt = width[0] * PT_PER_UNIT[width[1]]
        return (width_pt / view_width if view_width else PT_PER_UNIT[width[1]]), width_pt, True
    if view_width:
        return 1.0, view_width, False  # unitless: assume 1 user unit = 1 pt
    return 1.0, None, False


def audit_svg(
    data: bytes,
    min_pt: float = 5.0,
    max_pt: float = 7.0,
    max_width_mm: float = MM_DOUBLE,
) -> dict[str, object]:
    findings: list[Finding] = []
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        return {"auditable": False, "error": "DTD or entity declarations are not supported", "findings": []}
    try:
        root = ET.fromstring(data)  # nosec B314 - DTDs and entities rejected above
    except ET.ParseError as exc:
        return {"auditable": False, "error": f"not well-formed XML: {exc}", "findings": []}
    if local(root.tag) != "svg":
        return {"auditable": False, "error": "root element is not <svg>", "findings": []}

    unit_scale, width_pt, units_known = canvas_scale(root)
    if not units_known:
        findings.append(
            Finding("WARN", "canvas.units", "width has no physical unit; assuming 1 user unit = 1 pt")
        )
    width_mm = width_pt * 25.4 / 72 if width_pt else None
    if width_mm is None:
        findings.append(Finding("WARN", "canvas.size", "no width or viewBox; final size unknown"))
    else:
        if width_mm > max_width_mm + 0.5:
            findings.append(
                Finding("FAIL", "canvas.width", f"width {width_mm:.1f} mm exceeds {max_width_mm:g} mm")
            )
        elif min(abs(width_mm - MM_SINGLE), abs(width_mm - MM_DOUBLE)) > 2.0:
            findings.append(
                Finding("WARN", "canvas.width", f"width {width_mm:.1f} mm is not 89 mm or 183 mm")
            )

    view_box = [float(n) for n in re.findall(NUMBER, root.get("viewBox") or "")]
    sizes: list[float] = []
    texts = 0

    def walk(element: ET.Element, scale: float, font_size: float | None, parent_tag: str) -> None:
        nonlocal texts
        tag = local(element.tag)
        if tag in FORBIDDEN:
            findings.append(Finding(FORBIDDEN[tag], "forbidden", f"<{tag}> is not allowed in a production schematic"))
        for key, value in element.attrib.items():
            if local(key) == "href" and not (value.startswith("#") or value.startswith("data:")):
                findings.append(Finding("FAIL", "external-ref", f"external reference: {value[:60]}"))
        scale *= transform_scale(element)
        declared = style_value(element, "font-size")
        if declared:
            length = parse_length(declared)
            if length:
                font_size = length[0] * (PT_PER_UNIT[length[1]] / unit_scale if PT_PER_UNIT.get(length[1]) else 1.0)
        if tag == "text" or (tag == "tspan" and parent_tag != "text"):
            has_text = "".join(element.itertext()).strip()
            if has_text:
                texts += 1
                if font_size is None:
                    findings.append(
                        Finding("WARN", "text.size", f"font-size not set for {has_text[:30]!r}; SVG default is 16 units")
                    )
                else:
                    effective = font_size * scale * unit_scale
                    sizes.append(effective)
                    if effective < min_pt - 1e-6:
                        findings.append(
                            Finding("FAIL", "text.small", f"{has_text[:30]!r} is {effective:.2f} pt (< {min_pt:g} pt)")
                        )
                    elif effective > max_pt + 1e-6:
                        findings.append(
                            Finding("WARN", "text.large", f"{has_text[:30]!r} is {effective:.2f} pt (> {max_pt:g} pt)")
                        )
                if len(view_box) == 4 and scale == 1.0:
                    try:
                        x, y = float(element.get("x", "nan")), float(element.get("y", "nan"))
                    except ValueError:
                        x = y = float("nan")
                    if x == x and y == y and not (
                        view_box[0] <= x <= view_box[0] + view_box[2]
                        and view_box[1] <= y <= view_box[1] + view_box[3]
                    ):
                        findings.append(Finding("FAIL", "text.off-canvas", f"{has_text[:30]!r} is anchored outside the viewBox"))
        for child in element:
            walk(child, scale, font_size, tag)

    walk(root, 1.0, None, "")
    if not texts:
        findings.append(Finding("WARN", "text.none", "no <text> found; text may be outlined, which journals reject"))
    return {
        "auditable": True,
        "width_mm": width_mm,
        "text_count": texts,
        "minimum_found_pt": min(sizes) if sizes else None,
        "maximum_found_pt": max(sizes) if sizes else None,
        "thresholds": {"min_pt": min_pt, "max_pt": max_pt, "max_width_mm": max_width_mm},
        "findings": [asdict(f) for f in findings],
    }


def verdict(result: dict[str, object]) -> str:
    if not result["auditable"]:
        return "NOT AUDITABLE"
    severities = {f["severity"] for f in result["findings"]}  # type: ignore[index]
    return "FAIL" if "FAIL" in severities else "PASS WITH WARNINGS" if "WARN" in severities else "PASS"


def render_text(path: Path, result: dict[str, object]) -> str:
    lines = ["Nature Figure SVG Schematic Audit", f"svg: {path}"]
    if not result["auditable"]:
        lines.append(f"error: {result['error']}")
    else:
        width = result["width_mm"]
        lines.append(f"width: {width:.1f} mm" if width else "width: unknown")
        lines.append(f"text elements: {result['text_count']}")
        if result["minimum_found_pt"] is not None:
            lines.append(f"text size: {result['minimum_found_pt']:.2f} to {result['maximum_found_pt']:.2f} pt")
        for f in result["findings"]:  # type: ignore[union-attr]
            lines.append(f"[{f['severity']}] {f['kind']}: {f['message']}")
    lines.append(f"verdict: {verdict(result)}")
    lines.append("note: overlaps, crossings and outlined text are not detected; inspect the render at final size")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("svg", type=Path, help="SVG schematic")
    parser.add_argument("--min-pt", type=float, default=5.0, help="minimum text size in points")
    parser.add_argument("--max-pt", type=float, default=7.0, help="maximum ordinary text size in points")
    parser.add_argument("--max-width-mm", type=float, default=MM_DOUBLE, help="maximum canvas width in mm")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.min_pt <= 0 or args.max_pt < args.min_pt or args.max_width_mm <= 0:
        print("error: thresholds must be positive and --max-pt >= --min-pt", file=sys.stderr)
        return 2
    try:
        data = args.svg.read_bytes()
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    result = audit_svg(data, args.min_pt, args.max_pt, args.max_width_mm)
    if args.json:
        print(json.dumps({"svg": str(args.svg), "verdict": verdict(result), **result}, indent=2, ensure_ascii=False))
    else:
        print(render_text(args.svg, result))
    if not result["auditable"]:
        return 2
    return 1 if verdict(result) == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
