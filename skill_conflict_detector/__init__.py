"""Hermes Skill Conflict Detector.

Scans a directory of Hermes Agent SKILL.md files, parses their frontmatter,
and detects:

1. Naming conflicts — duplicate skill names
2. Broken supersedes chains — A supersedes B but B doesn't declare superseded_by
3. Supersedes cycles — circular dependency in supersedes declarations
4. Orphaned deprecated skills — marked deprecated without an active replacement
5. Trigger overlap without relationship — same trigger keywords, no declared link
6. Missing metadata — skills missing version, status, or other required fields
"""

__version__ = "0.1.0"
