"""Tests for the Hermes Skill Conflict Detector."""

import json
import tempfile
from pathlib import Path

from skill_conflict_detector.scanner import (
    parse_frontmatter,
    scan_skills_directory,
)
from skill_conflict_detector.analyzer import (
    detect_naming_conflicts,
    detect_broken_supersedes_chains,
    detect_orphaned_deprecated,
    detect_trigger_overlap,
    detect_missing_metadata,
)


def test_parse_frontmatter_basic():
    """Parse a simple SKILL.md frontmatter."""
    content = """---
name: my-skill
version: 1.0.0
status: active
---

# Body text
"""
    fm = parse_frontmatter(content)
    assert fm.get("name") == "my-skill"
    assert fm.get("version") == "1.0.0"
    assert fm.get("status") == "active"


def test_parse_frontmatter_list():
    """Parse frontmatter with list fields."""
    content = """---
name: list-skill
triggers:
  - trigger one
  - trigger two
supersedes:
  - old-skill
tags: [tag1, tag2]
---
"""
    fm = parse_frontmatter(content)
    assert fm.get("name") == "list-skill"
    assert fm.get("triggers") == ["trigger one", "trigger two"]
    assert fm.get("tags") == ["tag1", "tag2"]


def test_parse_frontmatter_nested():
    """Parse frontmatter with nested metadata."""
    content = """---
name: nested-skill
metadata:
  hermes:
    tags: [python, automation]
    config:
      - key: some.setting
---
"""
    fm = parse_frontmatter(content)
    meta = fm.get("metadata", {})
    assert isinstance(meta, dict)
    hermes = meta.get("hermes", {})
    assert isinstance(hermes, dict)
    assert hermes.get("tags") == ["python", "automation"]


def test_parse_frontmatter_no_frontmatter():
    """Handle SKILL.md with no frontmatter."""
    content = "# Just a heading\n\nSome text"
    fm = parse_frontmatter(content)
    assert fm == {}


def test_parse_frontmatter_multiline_description():
    """Parse frontmatter with multiline description (| style)."""
    content = """---
name: multi-line
description: |
  This is a multi-line
  description that spans
  several lines in the frontmatter
---
"""
    fm = parse_frontmatter(content)
    assert "multi-line" in fm.get("description", "")


def test_naming_conflict_found():
    """Detect duplicate skill names."""
    skills = [
        {"name": "duplicate", "path": "/a/SKILL.md"},
        {"name": "unique", "path": "/b/SKILL.md"},
        {"name": "duplicate", "path": "/c/SKILL.md"},
    ]
    issues = detect_naming_conflicts(skills)
    assert len(issues) == 1
    assert issues[0]["type"] == "naming_conflict"
    assert issues[0]["severity"] == "ERROR"


def test_naming_conflict_clean():
    """No naming conflict when names are unique."""
    skills = [
        {"name": "skill-a", "path": "/a/SKILL.md"},
        {"name": "skill-b", "path": "/b/SKILL.md"},
    ]
    issues = detect_naming_conflicts(skills)
    assert len(issues) == 0


def test_broken_supersedes_forward():
    """A.supersedes B but B has no superseded_by."""
    skills = [
        {"name": "new-skill", "supersedes": ["old-skill"], "path": "/a/SKILL.md"},
        {"name": "old-skill", "superseded_by": "", "path": "/b/SKILL.md"},
    ]
    issues = detect_broken_supersedes_chains(skills)
    forward_issues = [i for i in issues if i["type"] == "broken_forward_supersedes"]
    assert len(forward_issues) == 1


def test_broken_supersedes_backward():
    """B.superseded_by = A but A doesn't list B."""
    skills = [
        {"name": "new-skill", "supersedes": [], "path": "/a/SKILL.md"},
        {"name": "old-skill", "superseded_by": "new-skill", "path": "/b/SKILL.md"},
    ]
    issues = detect_broken_supersedes_chains(skills)
    backward_issues = [i for i in issues if i["type"] == "broken_backward_supersedes"]
    assert len(backward_issues) == 1


def test_correct_supersedes_no_issues():
    """A.supersedes B AND B.superseded_by = A = no issues and no false cycle."""
    skills = [
        {"name": "new-skill", "supersedes": ["old-skill"], "path": "/a/SKILL.md", "dir": "/a", "category": "", "version": "2.0.0", "status": "active", "superseded_by": "", "description": "New version", "tags": [], "triggers": [], "platforms": [], "raw_frontmatter": {}, "body_preview": "", "body": ""},
        {"name": "old-skill", "superseded_by": "new-skill", "path": "/b/SKILL.md", "dir": "/b", "category": "", "version": "1.0.0", "status": "deprecated", "supersedes": [], "description": "Old version", "tags": [], "triggers": [], "platforms": [], "raw_frontmatter": {}, "body_preview": "", "body": ""},
    ]
    issues = detect_broken_supersedes_chains(skills)
    cycles = [i for i in issues if i["type"] == "supersedes_cycle"]
    assert len(cycles) == 0, "Correct supersedes + superseded_by should not be a cycle"


def test_missing_metadata_detects():
    """Detect missing version and status."""
    skills = [
        {"name": "no-meta", "path": "/a/SKILL.md", "version": "", "status": "active", "description": "Has desc", "raw_frontmatter": {"name": "no-meta"}},
    ]
    issues = detect_missing_metadata(skills)
    types = {i["type"] for i in issues}
    assert "missing_version" in types


def test_orphaned_deprecated():
    """Deprecated skill with no replacement is orphaned."""
    skills = [
        {"name": "dead-skill", "status": "deprecated", "path": "/a/SKILL.md", "version": "1.0.0", "superseded_by": "", "supersedes": []},
        {"name": "unrelated", "status": "active", "supersedes": [], "superseded_by": ""},
    ]
    issues = detect_orphaned_deprecated(skills)
    assert len(issues) == 1
    assert issues[0]["type"] == "orphaned_deprecated"


def test_scan_real_directory():
    """Scan a real skills directory with a temp directory structure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a valid skill
        skill_dir = Path(tmpdir) / "my-category" / "test-skill"
        skill_dir.mkdir(parents=True)
        sk_file = skill_dir / "SKILL.md"
        sk_file.write_text("""---
name: test-skill
version: 1.0.0
status: active
description: A test skill for unit testing
triggers:
  - test
  - unittest
---
# Test Skill
""", encoding="utf-8")

        skills = scan_skills_directory(tmpdir)
        assert len(skills) >= 1
        test_skill = [s for s in skills if s["name"] == "test-skill"]
        assert len(test_skill) == 1
        assert test_skill[0]["version"] == "1.0.0"
        assert test_skill[0]["status"] == "active"
        assert "test" in test_skill[0]["triggers"]


def test_integration():
    """Run all checks on a minimal skills directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        # Create skill a (active)
        (tmp / "cat1/skill-a").mkdir(parents=True)
        (tmp / "cat1/skill-a/SKILL.md").write_text("""---
name: skill-a
version: 2.0.0
status: active
description: This skill supersedes skill-b
triggers:
  - domain-specific-task
supersedes:
  - skill-b
---
""", encoding="utf-8")

        # Create skill b (deprecated)
        (tmp / "cat1/skill-b").mkdir(parents=True)
        (tmp / "cat1/skill-b/SKILL.md").write_text("""---
name: skill-b
version: 1.0.0
status: deprecated
description: Old version, superseded by skill-a
superseded_by: skill-a
---
""", encoding="utf-8")

        # Create skill c (orphaned)
        (tmp / "cat2/skill-c").mkdir(parents=True)
        (tmp / "cat2/skill-c/SKILL.md").write_text("""---
name: skill-c
version: 1.0.0
status: deprecated
description: Deprecated with no replacement
---
""", encoding="utf-8")

        skills = scan_skills_directory(tmpdir)

        naming = detect_naming_conflicts(skills)
        assert len(naming) == 0

        supersedes = detect_broken_supersedes_chains(skills)
        assert len(supersedes) == 0  # skill-a → skill-b is correct

        orphans = detect_orphaned_deprecated(skills)
        assert len(orphans) == 1  # skill-c is orphaned
        assert orphans[0]["details"]["skill_name"] == "skill-c"
