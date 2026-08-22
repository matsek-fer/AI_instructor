from ai_learner.subagents.svg_agent import SVGAgent, inspect_svg

from conftest import FakeLLM

GOOD_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<rect x="10" y="10" width="50" height="30" fill="#ccc"/>'
    '<text x="20" y="60" font-size="12">label</text>'
    "</svg>"
)


# -- static inspector ------------------------------------------------------

def test_inspect_accepts_good_svg():
    result = inspect_svg(GOOD_SVG)
    assert result.ok, result.issues


def test_inspect_rejects_malformed_xml():
    result = inspect_svg("<svg><rect</svg>")
    assert not result.ok
    assert "not well-formed" in result.issues[0]


def test_inspect_rejects_non_svg_root():
    result = inspect_svg("<div>hi</div>")
    assert not result.ok


def test_inspect_rejects_missing_viewbox():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><rect x="1" y="1"/></svg>'
    result = inspect_svg(svg)
    assert any("viewBox" in issue for issue in result.issues)


def test_inspect_rejects_script_and_event_handlers():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<script>alert(1)</script>'
        '<rect x="1" y="1" onclick="evil()"/>'
        "</svg>"
    )
    result = inspect_svg(svg)
    assert any("script" in issue for issue in result.issues)
    assert any("onclick" in issue for issue in result.issues)


def test_inspect_rejects_external_references():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'xmlns:xlink="http://www.w3.org/1999/xlink" viewBox="0 0 10 10">'
        '<image xlink:href="http://evil/x.png"/>'
        "</svg>"
    )
    result = inspect_svg(svg)
    assert any("image" in issue for issue in result.issues)
    assert any("href" in issue for issue in result.issues)


def test_inspect_rejects_out_of_bounds_elements():
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<circle cx="500" cy="50" r="5"/>'
        "</svg>"
    )
    result = inspect_svg(svg)
    assert any("outside the viewBox" in issue for issue in result.issues)


def test_inspect_rejects_empty_drawing():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"></svg>'
    result = inspect_svg(svg)
    assert any("no drawable content" in issue for issue in result.issues)


# -- generate/inspect/correct loop ----------------------------------------

def test_agent_returns_approved_svg_first_try():
    llm = FakeLLM([
        {"svg": GOOD_SVG},                      # generate
        {"approved": True, "issues": [], "corrected_svg": ""},  # self-review
    ])
    agent = SVGAgent(llm)
    assert agent.create("math", "Vectors", "two arrows") == GOOD_SVG
    assert len(llm.calls) == 2


def test_agent_revises_after_static_failure():
    llm = FakeLLM([
        {"svg": "<broken"},                     # generate: invalid
        {"svg": GOOD_SVG},                      # revise
        {"approved": True, "issues": [], "corrected_svg": ""},  # self-review
    ])
    agent = SVGAgent(llm)
    assert agent.create("math", "Vectors", "two arrows") == GOOD_SVG
    # The revision prompt must carry the concrete validator issues.
    assert "not well-formed" in llm.calls[1].prompt


def test_agent_applies_self_review_correction():
    corrected = GOOD_SVG.replace("label", "better label")
    llm = FakeLLM([
        {"svg": GOOD_SVG},
        {"approved": False, "issues": ["label unclear"], "corrected_svg": corrected},
        {"approved": True, "issues": [], "corrected_svg": ""},
    ])
    agent = SVGAgent(llm)
    assert agent.create("math", "Vectors", "two arrows") == corrected


def test_agent_gives_up_gracefully():
    llm = FakeLLM([
        {"svg": "<broken"},
        {"svg": "<broken"},
        {"svg": "<broken"},
        {"svg": "<broken"},
    ])
    agent = SVGAgent(llm, max_revisions=3)
    assert agent.create("math", "Vectors", "two arrows") is None
