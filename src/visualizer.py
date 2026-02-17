"""Concept graph visualization: Mermaid diagram and interactive D3.js HTML."""

import html
import json
from pathlib import Path


# ---------------------------------------------------------------------------
# Mermaid flowchart
# ---------------------------------------------------------------------------

_EDGE_STYLE = {
    "depends_on": "-->",
    "contradicts": "x--x",
    "evolves_into": "-.->",
}

_EDGE_LABEL = {
    "depends_on": "depends on",
    "contradicts": "contradicts",
    "evolves_into": "evolves into",
}


def _mermaid_id(concept_id: str) -> str:
    """Sanitise a concept ID for Mermaid (alphanumeric + underscore only)."""
    return "".join(c if c.isalnum() or c == "_" else "_" for c in concept_id)


def generate_mermaid(concept_graph: dict) -> str:
    """Return a Mermaid flowchart string for the concept graph."""
    concepts = concept_graph.get("concepts", [])
    relations = concept_graph.get("relations", [])

    if not concepts:
        return ""

    # Build a set of known concept IDs for validation
    known_ids = set()
    for c in concepts:
        if isinstance(c, dict):
            known_ids.add(c.get("id", ""))

    lines = ["```mermaid", "flowchart TD"]

    # Node definitions
    for c in concepts:
        if isinstance(c, str):
            continue
        mid = _mermaid_id(c.get("id", "unknown"))
        name = c.get("name", c.get("id", "?"))
        # Mermaid uses quotes for labels with special chars
        safe_name = name.replace('"', "'")
        lines.append(f'    {mid}["{safe_name}"]')

    lines.append("")

    # Edge definitions
    for r in relations:
        if isinstance(r, str):
            continue
        src = r.get("source", "")
        tgt = r.get("target", "")
        rtype = r.get("relation_type", "depends_on")

        if src not in known_ids or tgt not in known_ids:
            continue

        arrow = _EDGE_STYLE.get(rtype, "-->")
        label = _EDGE_LABEL.get(rtype, rtype)
        src_m = _mermaid_id(src)
        tgt_m = _mermaid_id(tgt)
        lines.append(f"    {src_m} {arrow}|{label}| {tgt_m}")

    # Style classes
    lines.append("")
    lines.append("    classDef default fill:#f9f9f9,stroke:#333,stroke-width:1px")
    lines.append("```")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Interactive D3.js HTML
# ---------------------------------------------------------------------------

_D3_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Concept Graph — {title}</title>
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
         background: #0a0a0a; color: #e0e0e0; overflow: hidden; }
  svg { width: 100vw; height: 100vh; display: block; }
  .link {{ stroke-opacity: 0.6; fill: none; }}
  .link-depends {{ stroke: #4a9eff; }}
  .link-contradicts {{ stroke: #ff4a4a; stroke-dasharray: 6,3; }}
  .link-evolves {{ stroke: #4aff8b; stroke-dasharray: 2,4; }}
  .node circle {{ stroke: #fff; stroke-width: 1.5px; cursor: grab; }}
  .node circle:hover {{ stroke-width: 3px; }}
  .node text {{ fill: #e0e0e0; font-size: 11px; pointer-events: none;
               text-anchor: middle; dominant-baseline: central; }}
  .link-label {{ fill: #888; font-size: 9px; pointer-events: none; }}
  #tooltip {{ position: fixed; background: #1a1a2e; border: 1px solid #333;
              border-radius: 6px; padding: 10px 14px; max-width: 350px;
              font-size: 12px; line-height: 1.5; pointer-events: none;
              display: none; z-index: 10; box-shadow: 0 4px 12px rgba(0,0,0,0.5); }}
  #tooltip h3 {{ color: #4a9eff; margin-bottom: 4px; font-size: 13px; }}
  #tooltip .chunk {{ color: #888; font-size: 10px; }}
  #tooltip .desc {{ color: #ccc; margin-top: 4px; }}
  #legend {{ position: fixed; bottom: 16px; left: 16px; background: #1a1a2e;
             border: 1px solid #333; border-radius: 6px; padding: 10px 14px;
             font-size: 11px; line-height: 1.8; }}
  #legend span {{ display: inline-block; width: 24px; height: 3px;
                  vertical-align: middle; margin-right: 6px; }}
  #title {{ position: fixed; top: 16px; left: 16px; font-size: 16px;
            font-weight: 600; color: #4a9eff; }}
</style>
</head>
<body>
<div id="title">{title}</div>
<div id="tooltip"></div>
<div id="legend">
  <div><span style="background:#4a9eff"></span>depends on</div>
  <div><span style="background:#ff4a4a;border-top:2px dashed #ff4a4a;height:0"></span>contradicts</div>
  <div><span style="background:#4aff8b;border-top:2px dotted #4aff8b;height:0"></span>evolves into</div>
</div>
<svg></svg>
<script src="https://d3js.org/d3.v7.min.js"></script>
<script>
const graphData = {graph_json};

const svg = d3.select("svg");
const width = window.innerWidth;
const height = window.innerHeight;

const g = svg.append("g");

// Zoom
svg.call(d3.zoom()
  .scaleExtent([0.2, 5])
  .on("zoom", (event) => g.attr("transform", event.transform)));

const linkColorClass = {{
  "depends_on": "link-depends",
  "contradicts": "link-contradicts",
  "evolves_into": "link-evolves",
}};

const simulation = d3.forceSimulation(graphData.nodes)
  .force("link", d3.forceLink(graphData.links).id(d => d.id).distance(140))
  .force("charge", d3.forceManyBody().strength(-400))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collision", d3.forceCollide().radius(40));

// Links
const link = g.append("g")
  .selectAll("line")
  .data(graphData.links)
  .join("line")
  .attr("class", d => "link " + (linkColorClass[d.relation_type] || "link-depends"))
  .attr("stroke-width", 1.5);

// Link labels
const linkLabel = g.append("g")
  .selectAll("text")
  .data(graphData.links)
  .join("text")
  .attr("class", "link-label")
  .text(d => d.relation_type.replace("_", " "));

// Nodes
const nodeRadius = d => 8 + Math.min(d.quotes, 4) * 3;
const nodeColor = d3.scaleOrdinal(d3.schemeTableau10);

const node = g.append("g")
  .selectAll("g")
  .data(graphData.nodes)
  .join("g")
  .attr("class", "node")
  .call(d3.drag()
    .on("start", dragstarted)
    .on("drag", dragged)
    .on("end", dragended));

node.append("circle")
  .attr("r", nodeRadius)
  .attr("fill", (d, i) => nodeColor(d.chunk));

node.append("text")
  .text(d => d.name.length > 20 ? d.name.slice(0, 18) + "…" : d.name)
  .attr("dy", d => -(nodeRadius(d) + 6));

// Tooltip
const tooltip = d3.select("#tooltip");

node.on("mouseover", (event, d) => {{
  tooltip.style("display", "block")
    .html(`<h3>${{d.name}}</h3><div class="chunk">${{d.chunk}}</div><div class="desc">${{d.description}}</div>`);
}})
.on("mousemove", (event) => {{
  tooltip.style("left", (event.clientX + 14) + "px")
         .style("top", (event.clientY - 14) + "px");
}})
.on("mouseout", () => tooltip.style("display", "none"));

simulation.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  linkLabel.attr("x", d => (d.source.x + d.target.x) / 2)
           .attr("y", d => (d.source.y + d.target.y) / 2);
  node.attr("transform", d => `translate(${{d.x}},${{d.y}})`);
}});

function dragstarted(event) {{
  if (!event.active) simulation.alphaTarget(0.3).restart();
  event.subject.fx = event.subject.x;
  event.subject.fy = event.subject.y;
}}
function dragged(event) {{
  event.subject.fx = event.x;
  event.subject.fy = event.y;
}}
function dragended(event) {{
  if (!event.active) simulation.alphaTarget(0);
  event.subject.fx = null;
  event.subject.fy = null;
}}
</script>
</body>
</html>
"""


def _concept_graph_to_d3(concept_graph: dict) -> dict:
    """Convert the concept graph into D3 force-directed graph format."""
    concepts = concept_graph.get("concepts", [])
    relations = concept_graph.get("relations", [])

    known_ids = set()
    nodes = []
    for c in concepts:
        if isinstance(c, str):
            continue
        cid = c.get("id", "")
        known_ids.add(cid)
        nodes.append({
            "id": cid,
            "name": c.get("name", cid),
            "description": html.escape(c.get("description", "")[:300]),
            "chunk": c.get("source_chunk", "?"),
            "quotes": len(c.get("original_quotes", [])),
        })

    links = []
    for r in relations:
        if isinstance(r, str):
            continue
        src = r.get("source", "")
        tgt = r.get("target", "")
        if src in known_ids and tgt in known_ids:
            links.append({
                "source": src,
                "target": tgt,
                "relation_type": r.get("relation_type", "depends_on"),
            })

    return {"nodes": nodes, "links": links}


def generate_d3_html(concept_graph: dict, title: str = "Concept Graph") -> str:
    """Return a self-contained HTML page with an interactive D3 force graph."""
    d3_data = _concept_graph_to_d3(concept_graph)
    graph_json = json.dumps(d3_data, ensure_ascii=False)
    safe_title = html.escape(title)
    return _D3_HTML_TEMPLATE.replace("{title}", safe_title).replace(
        "{graph_json}", graph_json
    )


# ---------------------------------------------------------------------------
# Public API — write both outputs to run_dir
# ---------------------------------------------------------------------------

def save_concept_graph_visuals(
    concept_graph: dict,
    run_dir: Path,
    book_title: str = "Concept Graph",
) -> list[Path]:
    """Generate and save Mermaid + D3 visualizations. Returns list of created files."""
    created = []

    # 1. Mermaid diagram as .md
    mermaid = generate_mermaid(concept_graph)
    if mermaid:
        md_path = run_dir / "03_concept_graph_visual.md"
        content = f"# Concept Graph — {book_title}\n\n{mermaid}\n"
        md_path.write_text(content, encoding="utf-8")
        created.append(md_path)

    # 2. Interactive D3 HTML
    concepts = concept_graph.get("concepts", [])
    if concepts:
        html_content = generate_d3_html(concept_graph, title=book_title)
        html_path = run_dir / "03_concept_graph.html"
        html_path.write_text(html_content, encoding="utf-8")
        created.append(html_path)

    return created
