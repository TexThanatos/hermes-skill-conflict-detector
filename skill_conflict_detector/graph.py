"""Generate skill relationship graphs — Mermaid and vis.js interactive HTML."""

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple


def build_relation_triples(skills: List[Dict]) -> List[Tuple[str, str, str]]:
    """Build (skill_a, relation, skill_b) triples from skills data."""
    triples = []
    name_map = {sk["name"]: sk for sk in skills}

    for sk in skills:
        name = sk["name"]
        for target in sk.get("supersedes", []):
            triples.append((name, "supersedes", target))
        if sk.get("superseded_by"):
            triples.append((name, "superseded_by", sk["superseded_by"]))

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
            shared = profiles[a]["platforms"] & profiles[b]["platforms"]
            if not shared:
                continue
            sk_a, sk_b = name_map.get(a, {}), name_map.get(b, {})
            if (a in sk_b.get("supersedes", []) or b in sk_a.get("supersedes", [])
                    or sk_a.get("superseded_by") == b or sk_b.get("superseded_by") == a):
                continue
            triples.append((a, "overlaps", b))
    return triples


def group_triples(triples):
    groups = defaultdict(list)
    for a, rel, b in triples:
        groups[rel].append((a, b))
    return dict(groups)


def _collect_connected_nodes(triples, focus_skill=None, max_depth=None):
    """Return set of nodes that have edges. Optionally BFS from focus_skill.

    If max_depth is set (e.g. 1), only include directly connected nodes.
    """
    all_nodes, adj = set(), defaultdict(set)
    for a, r, b in triples:
        all_nodes.add(a); all_nodes.add(b)
        adj[a].add(b); adj[b].add(a)
    if not focus_skill:
        return all_nodes
    if focus_skill not in all_nodes:
        return {focus_skill}
    visited, queue = {focus_skill}, [(focus_skill, 0)]
    while queue:
        n, d = queue.pop(0)
        if max_depth is not None and d >= max_depth:
            continue
        for nb in adj.get(n, set()):
            if nb not in visited:
                visited.add(nb)
                queue.append((nb, d + 1))
    return visited


# ── Mermaid ─────────────────────────────────────────────────────────────

def generate_mermaid_with_status(triples, skills=None):
    """Mermaid flowchart with node colors."""
    groups = group_triples(triples)
    name_map = {sk["name"]: sk for sk in (skills or [])}
    lines = ["```mermaid", "graph LR"]
    all_nodes = set()
    for r, pairs in groups.items():
        for a, b in pairs:
            all_nodes.add(a); all_nodes.add(b)
    for node in sorted(all_nodes):
        s = name_map.get(node, {}).get("status", "active")
        cls = "deprecated" if s == "deprecated" else "active"
        lines.append(f'  {node}[{node}]:::{cls}')
    arrow = {"supersedes": "-->|supersedes|", "superseded_by": "-.->|superseded_by|",
             "overlaps": "===|overlaps|"}
    for r, pairs in groups.items():
        for a, b in pairs:
            lines.append(f'  {a} {arrow.get(r, "---")} {b}')
    lines.append("  classDef active fill:#4ade80,stroke:#166534,color:#000")
    lines.append("  classDef deprecated fill:#fca5a5,stroke:#991b1b,color:#000")
    lines.append("```")
    return "\n".join(lines)


# ── Interactive vis.js HTML ─────────────────────────────────────────────

def generate_interactive_html(triples, skills, focus_skill=None, max_depth=None):
    """Interactive HTML with vis.js. Only shows nodes with relationships.

    If focus_skill is set, only show that skill's connected subgraph.
    max_depth limits BFS depth (1 = direct connections only).
    """
    groups = group_triples(triples)
    name_map = {sk["name"]: sk for sk in skills}
    connected = _collect_connected_nodes(triples, focus_skill, max_depth=max_depth)
    if not connected:
        return "<p>No relationships found.</p>"

    title = f"Skill Graph — {focus_skill}" if focus_skill else "Skill Relationship Graph"

    nodes_json = []
    for name in sorted(connected):
        sk = name_map.get(name, {})
        st = sk.get("status", "active")
        if st == "deprecated":
            bg, brd = "#fca5a5", "#991b1b"
        elif st == "active":
            bg, brd = "#4ade80", "#166534"
        else:
            bg, brd = "#fef08a", "#854d0e"
        hover = (f"<b>{name}</b><br>status: {st}<br>"
                 f"version: {sk.get('version', 'N/A')}<br>"
                 f"category: {sk.get('category', 'N/A')}")
        nodes_json.append({"id": name, "label": name,
                           "color": {"background": bg, "border": brd},
                           "title": hover, "shape": "box", "font": {"size": 14}})

    edges_json = []
    colors = {"supersedes": "#2563eb", "superseded_by": "#9333ea", "overlaps": "#d97706"}
    for rel, pairs in groups.items():
        for a, b in pairs:
            if a in connected and b in connected:
                edges_json.append({
                    "from": a, "to": b, "label": rel,
                    "color": {"color": colors.get(rel, "#666"), "highlight": "#fff"},
                    "dashes": rel == "superseded_by",
                    "width": 2 if rel == "supersedes" else 1,
                })

    n = json.dumps(nodes_json, ensure_ascii=False)
    e = json.dumps(edges_json, ensure_ascii=False)

    return f"""<!DOCTYPE html>
<html lang="zh">
<head><meta charset="utf-8">
<title>{title}</title>
<script src="https://unpkg.com/vis-network/styles/vis-network.min.css"></script>
<script src="https://unpkg.com/vis-data/peer/umd/vis-data.min.js"></script>
<script src="https://unpkg.com/vis-network/peer/umd/vis-network.min.js"></script>
<style>
  *{{margin:0;padding:0;box-sizing:border-box}}
  body{{font-family:-apple-system,'Segoe UI',sans-serif;background:#1e1e2e;overflow:hidden}}
  #graph{{width:100vw;height:100vh}}
  .hdr{{position:fixed;top:0;left:0;right:0;z-index:200;padding:10px 20px;
        background:rgba(30,30,46,.85);border-bottom:1px solid #45475a;
        color:#cdd6f4;display:flex;align-items:center;gap:12px}}
  .hdr h1{{font-size:16px;font-weight:600}}
  .hdr .sub{{font-size:12px;color:#6c7086}}
  .leg{{position:fixed;bottom:20px;left:20px;background:rgba(30,30,46,.9);
        padding:10px 14px;border-radius:8px;color:#cdd6f4;font-size:12px;
        border:1px solid #45475a;z-index:100;line-height:1.8}}
  .leg .ln{{display:inline-block;width:24px;height:2px;margin-right:6px;vertical-align:middle}}
  .leg .ds{{border-top:2px dashed;height:0}}
  .leg .dt{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:middle}}
</style></head>
<body>
<div class="hdr"><h1>{title}</h1><span class="sub">{len(connected)} skills</span></div>
<div id="graph"></div>
<div class="leg">
  <div><span class="ln" style="background:#2563eb"></span> supersedes</div>
  <div><span class="ln ds" style="border-color:#9333ea"></span> superseded_by</div>
  <div><span class="ln" style="background:#d97706;height:4px"></span> overlaps</div>
  <div style="margin-top:2px"><span class="dt" style="background:#4ade80"></span> active</div>
  <div><span class="dt" style="background:#fca5a5"></span> deprecated</div>
</div>
<script>
const nodes=new vis.DataSet({n}),edges=new vis.DataSet({e});
const container=document.getElementById('graph');
const data={{nodes,edges}};
const options={{
  nodes:{{font:{{color:'#1e1e2e',size:13,face:'monospace'}},borderWidth:2,
          margin:{{top:6,bottom:6,left:10,right:10}}}},
  edges:{{font:{{color:'#a6adc8',size:9,strokeWidth:0}},
          smooth:{{type:'curvedCW',roundness:.15}}}},
  physics:{{solver:'forceAtlas2Based',
            forceAtlas2Based:{{gravitationalConstant:-30,centralGravity:.005,
                              springLength:180,springConstant:.02,
                              damping:.4,avoidOverlap:.5}},
            stabilization:{{iterations:100,updateInterval:25}}}},
  interaction:{{hover:true,tooltipDelay:150,zoomView:true,
                dragView:true,dragNodes:true}}
}};
const net=new vis.Network(container,data,options);
net.once('stabilizationIterationsDone',()=>{{net.fit({{animation:true}})}});
</script></body></html>"""
