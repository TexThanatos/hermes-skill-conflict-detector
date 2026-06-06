#!/usr/bin/env python3
"""Command-line interface for Hermes Skill Conflict Detector."""

import argparse
import logging
import os
import sys

from .scanner import scan_skills_directory
from .analyzer import (
    detect_naming_conflicts,
    detect_broken_supersedes_chains,
    detect_orphaned_deprecated,
    detect_trigger_overlap,
    detect_missing_metadata,
    detect_similar_descriptions,
)
from .reporter import format_json_report, format_markdown_report, build_stats


def main():
    parser = argparse.ArgumentParser(
        description="Detect conflicts between Hermes Agent skills",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  skill-conflicts ~/.hermes/skills
  skill-conflicts ~/.hermes/skills --format json
  skill-conflicts ~/.hermes/skills --output report.md
  skill-conflicts ~/.hermes/skills --severity ERROR,WARNING
  skill-conflicts ~/.hermes/skills --skip supersedes,metadata
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
        help="Comma-separated minimum severities to include (default: ERROR,WARNING,INFO)",
    )
    parser.add_argument(
        "--skip",
        help="Comma-separated check types to skip: naming,supersedes,orphans,triggers,metadata,descriptions",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show verbose logging",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"skill-conflicts 0.1.0",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
    )

    # Parse severity filter
    allowed_severities = set(s.strip().upper() for s in args.severity.split(","))

    # Parse skip list
    skip_checks = set()
    if args.skip:
        skip_checks = set(s.strip().lower() for s in args.skip.split(","))

    # Map skip names to check functions
    check_map = {
        "naming": ("Naming conflicts", detect_naming_conflicts),
        "supersedes": ("Broken supersedes chains", detect_broken_supersedes_chains),
        "orphans": ("Orphaned deprecated skills", detect_orphaned_deprecated),
        "triggers": ("Trigger overlap", detect_trigger_overlap),
        "metadata": ("Missing metadata", detect_missing_metadata),
        "descriptions": ("Similar descriptions", detect_similar_descriptions),
    }

    skip_names = {"naming", "supersedes", "orphans", "triggers", "metadata", "descriptions"}
    unknown_skips = skip_checks - skip_names
    if unknown_skips:
        print(f"Warning: Unknown check types to skip: {unknown_skips}", file=sys.stderr)
        print(f"Valid types: {', '.join(sorted(skip_names))}", file=sys.stderr)

    skills_dir = os.path.abspath(args.skills_dir)

    if not os.path.isdir(skills_dir):
        print(f"Error: Skills directory not found: {skills_dir}", file=sys.stderr)
        sys.exit(1)

    # Scan
    print(f"Scanning skills in: {skills_dir}", file=sys.stderr)
    skills = scan_skills_directory(skills_dir)
    print(f"Found {len(skills)} skills", file=sys.stderr)

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
    filtered_issues = [
        i for i in all_issues
        if i["severity"] in allowed_severities
    ]

    # Build stats
    stats = build_stats(filtered_issues, len(skills), skills_dir)

    # Generate report
    if args.format == "json":
        report = format_json_report(filtered_issues, stats)
    else:
        report = format_markdown_report(filtered_issues, stats)

    # Output
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"\nReport written to: {args.output}", file=sys.stderr)
    else:
        print()
        print(report)


if __name__ == "__main__":
    main()
