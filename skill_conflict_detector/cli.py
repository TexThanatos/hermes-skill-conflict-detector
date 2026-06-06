#!/usr/bin/env python3
"""Command-line interface for Hermes Skill Conflict Detector."""

import argparse
import logging
import os
import sys
import time

from .scanner import scan_skills_directory
from .analyzer import (
    detect_naming_conflicts,
    detect_broken_supersedes_chains,
    detect_orphaned_deprecated,
    detect_trigger_overlap,
    detect_missing_metadata,
    detect_similar_descriptions,
    detect_body_conflicts_deep,
)
from .reporter import format_json_report, format_markdown_report, build_stats
from .cache import (
    find_changed_skills,
    update_skill_hash,
    save_scan_result,
    get_last_scan,
    update_skill_relations,
    get_related_skills,
    cache_stats,
    clear_cache,
)
from .graph import (
    build_relation_triples,
    generate_mermaid_with_status,
    generate_interactive_html,
    _collect_connected_nodes,
)


def main():
    parser = argparse.ArgumentParser(
        description="Detect conflicts between Hermes Agent skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  skill-conflicts ~/.hermes/skills
  skill-conflicts ~/.hermes/skills --cache          # incremental scan
  skill-conflicts ~/.hermes/skills --cache --full    # force full rescan
  skill-conflicts ~/.hermes/skills --deep            # body content analysis
  skill-conflicts ~/.hermes/skills --graph           # shallow (default)
  skill-conflicts ~/.hermes/skills --graph --graph-for xianyu-publish
  skill-conflicts ~/.hermes/skills --graph-html --recursive  # full expansion
  skill-conflicts ~/.hermes/skills --cache-stats     # show cache status
  skill-conflicts ~/.hermes/skills --cache-clear     # clear all cached data
        """,
    )

    parser.add_argument(
        "skills_dir",
        nargs="?",
        default=os.path.expanduser("~/.hermes/skills"),
        help="Path to Hermes skills directory (default: ~/.hermes/skills)",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["markdown", "json"],
        default="markdown",
        help="Output format (default: markdown)",
    )
    parser.add_argument(
        "--output", "-o",
        help="Write report to file instead of stdout",
    )
    parser.add_argument(
        "--severity",
        default="ERROR,WARNING,INFO",
        help="Comma-separated severities to include (default: ERROR,WARNING,INFO)",
    )
    parser.add_argument(
        "--skip",
        help="Comma-separated checks to skip: naming,supersedes,orphans,triggers,metadata,descriptions,body",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose logging",
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="Analyze skill body content for tool chain & method conflicts",
    )
    parser.add_argument(
        "--cache",
        action="store_true",
        help="Use cache: incremental scan, re-scan only changed skills",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="With --cache: force full re-scan ignoring cache",
    )
    parser.add_argument(
        "--graph",
        action="store_true",
        help="Generate Mermaid relationship graph",
    )
    parser.add_argument(
        "--graph-html",
        action="store_true",
        help="Generate interactive vis.js relationship graph HTML",
    )
    parser.add_argument(
        "--graph-for",
        metavar="SKILL_NAME",
        help="With --graph or --graph-html: focus on a specific skill and its connections",
    )
    parser.add_argument(
        "--shallow",
        action="store_true",
        default=True,
        help="(default) Only scan/display direct (depth-1) connections, no recursion",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Expand scan/display to all connected skills (disables shallow default)",
    )
    parser.add_argument(
        "--cache-stats",
        action="store_true",
        help="Show cache statistics and exit",
    )
    parser.add_argument(
        "--cache-clear",
        action="store_true",
        help="Clear all cached data and exit",
    )
    parser.add_argument(
        "--related",
        metavar="SKILL_NAME",
        help="Show skills related to a specific skill (from cache)",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="skill-conflicts 0.2.0",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # Handle cache-only commands
    if args.cache_stats:
        stats = cache_stats()
        print(f"Cached skills: {stats['cached_skills']}")
        print(f"Scan history: {stats['scan_history']}")
        print(f"Relationships: {stats['relations']}")
        if stats['last_scan']:
            lt = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stats['last_scan']))
            print(f"Last scan: {lt}")
        else:
            print("Last scan: never")
        return

    if args.cache_clear:
        if clear_cache():
            print("Cache cleared.")
        else:
            print("No cache to clear.")
        return

    if args.related:
        rel = get_related_skills(args.related)
        print(f"Relations for '{args.related}':")
        for rtype, names in rel.items():
            if names:
                print(f"  {rtype}: {', '.join(names)}")
        return

    # Parse severity filter
    allowed_severities = set(s.strip().upper() for s in args.severity.split(","))
    skip_checks = set()
    if args.skip:
        skip_checks = set(s.strip().lower() for s in args.skip.split(","))

    skills_dir = os.path.abspath(args.skills_dir)
    if not os.path.isdir(skills_dir):
        print(f"Error: Skills directory not found: {skills_dir}", file=sys.stderr)
        sys.exit(1)

    # Scan
    scan_type = "full"
    print(f"Scanning skills in: {skills_dir}", file=sys.stderr)
    skills = scan_skills_directory(skills_dir)
    print(f"Found {len(skills)} skills", file=sys.stderr)

    # Cache check: find changed skills
    changed_skills = skills  # default: all skills
    changed_names = [sk["name"] for sk in skills]

    if args.cache and not args.full:
        changed, changed_n = find_changed_skills(skills)
        if not changed:
            last = get_last_scan()
            if last:
                print(f"  No changes since last scan.", file=sys.stderr)
                print(f"  Use --full to force re-scan.", file=sys.stderr)
                # Output last report
                if args.format == "json":
                    print(format_json_report(last["issues"], last["stats"]))
                else:
                    print(format_markdown_report(last["issues"], last["stats"]))
                return
        changed_skills = changed
        changed_names = changed_n
        scan_type = "incremental"
        print(f"  Changed skills: {len(changed_skills)}", file=sys.stderr)
        if len(changed_skills) < len(skills):
            print(f"  ({len(skills) - len(changed_skills)} unchanged, using cache)", file=sys.stderr)

    # Build check map
    check_map = {
        "naming": ("Naming conflicts", detect_naming_conflicts),
        "supersedes": ("Broken supersedes chains", detect_broken_supersedes_chains),
        "orphans": ("Orphaned deprecated skills", detect_orphaned_deprecated),
        "triggers": ("Trigger overlap", detect_trigger_overlap),
        "metadata": ("Missing metadata", detect_missing_metadata),
        "descriptions": ("Similar descriptions", detect_similar_descriptions),
    }
    if args.deep:
        check_map["body"] = ("Body content method conflicts", detect_body_conflicts_deep)

    skip_names = {"naming", "supersedes", "orphans", "triggers", "metadata", "descriptions", "body"}
    unknown_skips = skip_checks - skip_names
    if unknown_skips:
        print(f"Warning: Unknown check types to skip: {unknown_skips}", file=sys.stderr)
        print(f"Valid types: {', '.join(sorted(skip_names))}", file=sys.stderr)

    # Run checks
    all_issues = []
    for check_name, (check_label, check_fn) in check_map.items():
        if check_name in skip_checks:
            print(f"  Skipping: {check_label}", file=sys.stderr)
            continue
        print(f"  Running: {check_label}...", file=sys.stderr)
        issues = check_fn(skills)
        all_issues.extend(issues)
        if issues:
            print(f"    -> {len(issues)} issue(s) found", file=sys.stderr)

    # Filter by severity
    filtered_issues = [i for i in all_issues if i["severity"] in allowed_severities]

    # Build stats
    stats = build_stats(filtered_issues, len(skills), skills_dir)

    # Save cache
    if args.cache:
        for sk in skills:
            from .cache import compute_skill_hash
            fh, bh = compute_skill_hash(sk)
            update_skill_hash(sk, fh, bh)
        update_skill_relations(skills)
        save_scan_result(changed_names, filtered_issues, stats, scan_type)

    # Generate graph (Mermaid)
    if args.graph:
        triples = build_relation_triples(skills)
        print()
        print("## Skill Relationship Graph")
        print()
        if args.graph_for:
            connected = _collect_connected_nodes(triples, args.graph_for, max_depth=None if args.recursive else 1)
            filtered = [(a, r, b) for a, r, b in triples if a in connected and b in connected]
            print(generate_mermaid_with_status(filtered, skills))
        else:
            print(generate_mermaid_with_status(triples, skills))
        print()

    # Generate graph (interactive HTML)
    if args.graph_html:
        triples = build_relation_triples(skills)
        max_depth = None if args.recursive else 1
        html = generate_interactive_html(triples, skills, focus_skill=args.graph_for, max_depth=max_depth)
        graph_path = os.path.join(skills_dir, "..", "skill_relationship_graph.html")
        with open(graph_path, "w", encoding="utf-8") as f:
            f.write(html)
        print(f"\nInteractive graph written to: {graph_path}", file=sys.stderr)
        if args.graph_for:
            print(f"  (focused on: {args.graph_for})", file=sys.stderr)

    # Generate report
    if args.format == "json":
        report = format_json_report(filtered_issues, stats)
    else:
        report = format_markdown_report(filtered_issues, stats)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport written to: {args.output}", file=sys.stderr)
    else:
        print()
        print(report)


if __name__ == "__main__":
    main()
