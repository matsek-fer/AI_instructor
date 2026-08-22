"""SVG illustration sub-agent: generate, inspect own output, self-correct.

The agent runs generate -> inspect -> correct in a loop (spec §3, Phase 3).
Inspection is two-layered: a deterministic static check (valid XML, safe
content, elements inside the viewBox) that the model cannot talk its way past,
and a model self-review of the rendered layout. A drawing is embedded only
when both pass; on repeated failure the harness degrades gracefully to
prose-only teaching rather than embedding a broken diagram.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .. import prompts, schemas
from ..llm import LLM

SVG_NS = "http://www.w3.org/2000/svg"

# Elements that would make the note non-self-contained or unsafe to open.
_FORBIDDEN_TAGS = {"script", "foreignObject", "image", "use"}
_EVENT_ATTR = re.compile(r"^on", re.IGNORECASE)

# Numeric positional attributes checked against the viewBox.
_POSITIONAL_ATTRS = ("x", "y", "cx", "cy", "x1", "y1", "x2", "y2")


@dataclass
class InspectionResult:
    ok: bool
    issues: list[str] = field(default_factory=list)


def inspect_svg(source: str) -> InspectionResult:
    """Deterministic static validation of an SVG document."""
    issues: list[str] = []
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        return InspectionResult(False, [f"not well-formed XML: {exc}"])

    tag = root.tag.split("}")[-1]
    if tag != "svg":
        return InspectionResult(False, [f"root element is <{tag}>, expected <svg>"])
    if not root.tag.startswith("{" + SVG_NS + "}"):
        issues.append("missing SVG namespace (xmlns) on the root element")

    view_box = _parse_view_box(root.get("viewBox"))
    if view_box is None:
        issues.append("root <svg> has no usable viewBox")

    for element in root.iter():
        local = element.tag.split("}")[-1]
        if local in _FORBIDDEN_TAGS:
            issues.append(f"forbidden element <{local}> (must be self-contained)")
        for attr, value in element.attrib.items():
            attr_local = attr.split("}")[-1]
            if _EVENT_ATTR.match(attr_local):
                issues.append(f"forbidden event attribute {attr_local!r}")
            if attr_local == "href" or attr.endswith("}href"):
                issues.append("forbidden href reference (must be self-contained)")
        if view_box is not None:
            issue = _check_bounds(element, local, view_box)
            if issue:
                issues.append(issue)

    if view_box is not None and not any(
        el.tag.split("}")[-1] not in ("svg", "defs", "title", "desc", "style")
        for el in root.iter()
        if el is not root
    ):
        issues.append("SVG has no drawable content")

    return InspectionResult(not issues, issues)


def _parse_view_box(raw: str | None) -> tuple[float, float, float, float] | None:
    if not raw:
        return None
    try:
        parts = [float(p) for p in raw.replace(",", " ").split()]
    except ValueError:
        return None
    if len(parts) != 4 or parts[2] <= 0 or parts[3] <= 0:
        return None
    return parts[0], parts[1], parts[2], parts[3]


def _check_bounds(
    element: ET.Element, local: str, view_box: tuple[float, float, float, float]
) -> str | None:
    """Rough containment check: anchor coordinates must lie in the viewBox.

    A tolerance of 5% of the larger viewBox dimension absorbs stroke widths
    and text anchoring without letting elements drift meaningfully outside.
    """
    min_x, min_y, width, height = view_box
    tolerance = 0.05 * max(width, height)
    for attr in _POSITIONAL_ATTRS:
        raw = element.get(attr)
        if raw is None:
            continue
        try:
            value = float(raw)
        except ValueError:
            continue  # percentages / units: out of scope for the static pass
        if attr in ("x", "cx", "x1", "x2"):
            low, high = min_x - tolerance, min_x + width + tolerance
        else:
            low, high = min_y - tolerance, min_y + height + tolerance
        if not (low <= value <= high):
            return (
                f"<{local}> has {attr}={raw}, outside the viewBox "
                f"({min_x} {min_y} {width} {height})"
            )
    return None


class SVGAgent:
    def __init__(self, llm: LLM, max_revisions: int = 3):
        self._llm = llm
        self._max_revisions = max_revisions

    def create(self, topic: str, concept_title: str, description: str) -> str | None:
        """Produce a validated SVG, or None if it cannot be made sound."""
        svg = self._generate(topic, concept_title, description)
        for _ in range(self._max_revisions):
            static = inspect_svg(svg)
            if not static.ok:
                svg = self._revise(description, svg, static.issues)
                continue
            review = self._self_review(description, svg)
            if review is None:  # approved
                return svg
            svg = review
        # Last chance: accept only if the final revision passes the static check.
        return svg if inspect_svg(svg).ok else None

    def _generate(self, topic: str, concept_title: str, description: str) -> str:
        result = self._llm.structured(
            system=prompts.SVG_GENERATE,
            prompt=(
                f"Topic: {topic}\n"
                f"Concept: {concept_title}\n"
                f"Diagram to draw: {description}"
            ),
            schema=schemas.SVG,
        )
        return result.get("svg", "")

    def _revise(self, description: str, svg: str, issues: list[str]) -> str:
        listing = "\n".join(f"- {issue}" for issue in issues)
        result = self._llm.structured(
            system=prompts.SVG_GENERATE,
            prompt=(
                f"Diagram to draw: {description}\n"
                f"Your previous attempt failed validation:\n{listing}\n"
                f"Previous SVG:\n{svg}\n"
                f"Return the fully corrected SVG document."
            ),
            schema=schemas.SVG,
        )
        return result.get("svg", svg)

    def _self_review(self, description: str, svg: str) -> str | None:
        """Model inspects its own output; returns corrected SVG or None if approved."""
        result = self._llm.structured(
            system=prompts.SVG_INSPECT,
            prompt=f"The diagram was asked to show: {description}\nSVG source:\n{svg}",
            schema=schemas.SVG_REVIEW,
        )
        if result.get("approved"):
            return None
        corrected = result.get("corrected_svg", "")
        return corrected if corrected.strip() else svg
