"""Generate conflict reports in JSON and Markdown formats."""

import json
from datetime import datetime
from typing import Any, Dict, List


def format_json_report(issues: List[Dict], stats: Dict[str, Any]) -> str:
    """Return a JSON-formatted report."""
    report = {
        "generated_at": datetime.now().isoformat(),
        "statistics": stats,
        "issues": [
            {
                "severity": i["severity"],
                "type": i["type"],
                "message": i["message"],
                "details": i.get("details", {}),
            }
            for i in sorted(issues, key=lambda x: (_severity_sort_key(x["severity"]), x["type"]))
        ],
    }
    return json.dumps(report, indent=2, ensure_ascii=False)


def format_markdown_report(issues: List[Dict], stats: Dict[str, Any]) -> str:
    """Return a human-readable Markdown report."""
    lines: List[str] = []

    lines.append("# Hermes Skill Conflict Detector Report")
    lines.append("")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"| Metric | Value |")
    lines.append(f"|--------|-------|")
    lines.append(f"| Total skills scanned | {stats['total_skills']} |")
    lines.append(f"| Total issues found | {stats['total_issues']} |")
    lines.append(f"| Errors | {stats['by_severity'].get('ERROR', 0)} |")
    lines.append(f"| Warnings | {stats['by_severity'].get('WARNING', 0)} |")
    lines.append(f"| Info | {stats['by_severity'].get('INFO', 0)} |")
    lines.append(f"| Skills directory | {stats.get('skills_dir', '')} |")
    lines.append("")

    if not issues:
        lines.append("✅ **No issues found — your skills are clean!**")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Issues")
    lines.append("")

    by_severity: Dict[str, List[Dict]] = {}
    for issue in issues:
        by_severity.setdefault(issue["severity"], []).append(issue)

    for severity in ["ERROR", "WARNING", "INFO"]:
        sev_issues = by_severity.get(severity, [])
        if not sev_issues:
            continue

        sev_emoji = {"ERROR": "🔴", "WARNING": "🟡", "INFO": "🔵"}
        lines.append(f"### {sev_emoji.get(severity, '')} {severity} ({len(sev_issues)})")
        lines.append("")

        for issue in sev_issues:
            lines.append(f"**{issue['message']}**")
            details = issue.get("details", {})

            # Add structured details
            detail_items = []

            # Common detail fields
            if "skill_name" in details:
                detail_items.append(f"Skill: `{details['skill_name']}`")
            if "source" in details:
                detail_items.append(f"Source: `{details['source']}`")
            if "target" in details:
                detail_items.append(f"Target: `{details['target']}`")
            if "path" in details:
                detail_items.append(f"Path: `{details['path']}`")
            if "source_path" in details:
                detail_items.append(f"Path: `{details['source_path']}`")

            if detail_items:
                lines.append("  - " + "\n  - ".join(detail_items))

            # Suggestion
            suggestion = details.get("suggestion", "")
            if suggestion:
                lines.append("")
                lines.append(f"  💡 *Suggestion:* {suggestion}")

            # Common triggers for overlap issues
            common_triggers = details.get("common_triggers", [])
            if common_triggers:
                lines.append(f"  Common triggers: `{'`, `'.join(common_triggers)}`")

            lines.append("")

    # Add by-type breakdown
    lines.append("## Issues by Type")
    lines.append("")
    lines.append("| Type | Count | Severities |")
    lines.append("|------|-------|------------|")
    by_type: Dict[str, Dict[str, int]] = {}
    for issue in issues:
        by_type.setdefault(issue["type"], {})
        by_type[issue["type"]][issue["severity"]] = by_type[issue["type"]].get(issue["severity"], 0) + 1

    for t, sevs in sorted(by_type.items()):
        sev_str = ", ".join(f"{s}: {c}" for s, c in sorted(sevs.items()))
        total = sum(sevs.values())
        lines.append(f"| `{t}` | {total} | {sev_str} |")

    lines.append("")

    return "\n".join(lines)


def _severity_sort_key(severity: str) -> int:
    return {"ERROR": 0, "WARNING": 1, "INFO": 2}.get(severity, 99)


def build_stats(issues: List[Dict], total_skills: int, skills_dir: str) -> Dict[str, Any]:
    """Build statistics dictionary from issues list."""
    by_severity: Dict[str, int] = {}
    by_type: Dict[str, int] = {}

    for issue in issues:
        by_severity[issue["severity"]] = by_severity.get(issue["severity"], 0) + 1
        by_type[issue["type"]] = by_type.get(issue["type"], 0) + 1

    return {
        "total_skills": total_skills,
        "total_issues": len(issues),
        "by_severity": by_severity,
        "by_type": by_type,
        "skills_dir": skills_dir,
    }
