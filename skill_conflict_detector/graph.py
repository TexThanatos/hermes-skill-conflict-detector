"""Generate skill relationship graphs — Mermaid and vis.js interactive HTML."""

import json
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple


def build_relation_triples(skills: List[Dict]) -> List[Tuple[str, str, str]]:
    """Build list of (skill_a, relation, skill_b) triples from skills data.

    Relations: 'supersedes', 'overlaps' (same platform, no declaration)
    """
    triples = []

    # Direct declarations
    name_map = {sk["name"]: sk for sk in skills}
    for sk in skills:
        name = sk["name"]
        for target in sk.get("supersedes", []):
            triples.append((name, "supersedes", target))
        if sk.get("superseded_by"):
            triples.append((name, "superseded_by", sk["superseded_by"]))

    # Overlaps — skills sharing a platform with different tools
    from .analyzer import extract_body_profile

    profiles = {}
    for sk in skills:
        body = sk.get("body", "")
        if body:
            profiles[sk["name"]] = extract_body_profile(body)

    names = list(profiles.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            pa, pb = profiles[a], profiles[b]
            shared = pa["platforms"] & pb["platforms"]

            if not shared:
                continue

            # Only flag overlap if they haven't declared relationship
            sk_a = name_map.get(a, {})
            sk_b = name_map.get(b, {})
            has_rel = (
                a in sk_b.get("supersedes", [])
                or b in sk_a.get("supersedes", [])
                or sk_a.get("superseded_by") == b
                or sk_b.get("superseded_by") == a
            )
            if not has_rel and shared:
                triples.append((a, "overlaps", b))

    return triples


def group_triples(triples: List[Tuple[str, str, str]]) -> Dict[str, List[Tuple[str, str]]]:
    """Group triples by relation type.

    Returns: {'supersedes': [(a, b), ...], 'overlaps': [(a, b), ...]}
    """
    groups = defaultdict(list)
    for a, rel, b in triples:
        groups[rel].append((a, b))
    return dict(groups)


def _escape_mermaid_label(text: str) -> str:
    """Escape text for Mermaid node labels."""
    return text.replace('"', "'").replace("<", "&lt;").replace(">", "&gt;")


def generate_mermaid(triples: List[Tuple[str, str, str]]) -> str:
    """Generate a Mermaid flowchart from relation triples.

    Renders:
      - supersedes: solid arrow A --> B
      - superseded_by: dotted arrow A -.-> B
      - overlaps: thick line A === B
    """
    groups = group_triples(triples)
    all_nodes: Set[str] = set()
    for rel, pairs in groups.items():
        for a, b in pairs:
            all_nodes.add(a)
            all_nodes.add(b)

    lines = ["```mermaid", "graph LR"]

    # Style definitions
    lines.append("  classDef active fill:#4ade80,stroke:#166534,color:#000")
    lines.append("  classDef deprecated fill:#fca5a5,stroke:#991b1b,color:#000")
    lines.append("  classDef overlap fill:#fef08a,stroke:#854d0e,color:#000")

    for rel, pairs in groups.items():
        if rel == "supersedes":
            for a, b in pairs:
                lines.append(f'  {a} -->|supersedes| {b}')
        elif rel == "superseded_by":
            for a, b in pairs:
                lines.append(f'  {a} -.->|superseded_by| {b}')
        elif rel == "overlaps":
            for a, b in pairs:
                lines.append(f'  {a} ===|overlaps| {b}')

    lines.append("```")
    return "\n".join(lines)


def generate_mermaid_with_status(triples: List[Tuple[str, str, str]],
                                  skills: List[Dict]) -> str:
    """Generate Mermaid with node colors based on skill status."""
    groups = group_triples(triples)
    lines = ["```mermaid", "graph LR"]

    # Node declarations with status-based styling
    all_nodes: Set[str] = set()
    for rel, pairs in groups.items():
        for a, b in pairs:
            all_nodes.add(a)
            all_nodes.add(b)

    name_map = {sk["name"]: sk for sk in skills}
    for node in sorted(all_nodes):
        sk = name_map.get(node, {})
        status = sk.get("status", "active")
        if status == "deprecated":
            lines.append(f'  {node}[{node}]:::deprecated')
        else:
            lines.append(f'  {node}[{node}]:::active')

    for rel, pairs in groups.items():
        if rel == "supersedes":
            for a, b in pairs:
                lines.append(f'  {a} -->|supersedes| {b}')
        elif rel == "superseded_by":
            for a, b in pairs:
                lines.append(f'  {a} -.->|superseded_by| {b}')
        elif rel == "overlaps":
            for a, b in pairs:
                lines.append(f'  {a} ===|overlaps| {b}')

    lines.append("```")
    return "\n".join(lines)


def generate_interactive_html(triples: List[Tuple[str, str, str]],
                               skills: List[Dict]) -> str:
    """Generate a standalone HTML page with an interactive vis.js graph.

    Users can drag nodes, zoom, and hover for details.
    """
    groups = group_triples(triples)
    name_map = {sk["name"]: sk for sk in skills}

    # Build nodes
    nodes_set: Set[str] = set()
    for rel, pairs in groups.items():
        for a, b in pairs:
            nodes_set.add(a)
            nodes_set.add(b)

    nodes_json = []
    for name in sorted(nodes_set):
        sk = name_map.get(name, {})
        status = sk.get("status", "active")
        color = "#4ade80" if status == "active" else "#fca5a5" if status == "deprecated" else "#fef08a"
        title = f"{name}<br>status: {status}<br>version: {sk.get('version', 'N/A')}"
        nodes_json.append({"id": name, "label": name, "color": color, "title": title, "shape": "box"})

    # Build edges
    edges_json = []
    for rel, pairs in groups.items():
        color = {"supersedes": "#2563eb", "superseded_by": "#9333ea", "overlaps": "#d97706"}
        dashes = {"supersedes": False, "superseded_by": True, "overlaps": False}
        width = {"supersedes": 2, "superseded_by": 1, "overlaps": 4}
        for a, b in pairs:
            edges_json.append({
                "from": a, "to": b,
                "label": rel,
                "color": {"color": color.get(rel, "#666")},
                "dashes": dashes.get(rel, False),
                "width": width.get(rel, 1),
            })

    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Skill Relationship Graph</title>
<script src="https://unpkg.com/vis-network/styles/vis-network.min.css"></script>
<script src="https://unpkg.com/vis-data/peer/umd/vis-data.min.js"></script>
<script src="https://unpkg.com/vis-network/peer/umd/vis-network.min.js"></script>
<style>
  body { margin: 0; font-family: sans-serif; background: #1e1e2e; }
  #graph { width: 100vw; height: 100vh; }
  .legend { position: fixed; bottom: 20px; left: 20px; background: rgba(30,30,46,0.9);
            padding: 12px; border-radius: 8px; color: #cdd6f4; font-size: 13px;
            border: 1px solid #45475a; z-index: 100; }
  .legend span { display: inline-block; width: 20px; height: 3px; margin-right: 6px; vertical-align: middle; }
</style>
</head>
<body>
<div id="graph"></div>
<div class="legend">
  <div><span style="background:#2563eb"></span> supersedes</div>
  <div><span style="background:#9333ea;height:1px;border-top:2px dashed #9333ea"></span> superseded_by</div>
  <div><span style="background:#d97706;height:4px"></span> overlaps</div>
  <div style="margin-top:4px"><span style="background:#4ade80;width:12px;height:12px"></span> active</div>
  <div><span style="background:#fca5a5;width:12px;height:12px"></span> deprecated</div>
</div>
<script>
  const nodes = new vis.DataSet(""" + json.dumps(nodes_json, ensure_ascii=False) + """);
  const edges = new vis.DataSet(""" + json.dumps(edges_json, ensure_ascii=False) + """);
  const container = document.getElementById('graph');
  const data = { nodes, edges };
  const options = {
    nodes: { font: { color: '#cdd6f4', size: 14 }, borderWidth: 2 },
    edges: { font: { color: '#a6adc8', size: 10 }, smooth: { type: 'curvedCW', roundness: 0.2 } },
    physics: { solver: 'forceAtlas2Based', forceAtlas2Based: { gravitationalConstant: -40 } },
    interaction: { hover: true, tooltipDelay: 200 },
    background: '#1e1e2e',
  };
  new vis.Network(container, data, options);
</script>
</body>
</html>"""
    return html
