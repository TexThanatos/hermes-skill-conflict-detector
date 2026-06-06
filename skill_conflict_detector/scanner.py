"""Scan a Hermes skills directory and parse SKILL.md frontmatter."""

import os
import re
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Pattern to match YAML frontmatter between --- delimiters
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL | re.MULTILINE)


def parse_frontmatter(content: str) -> Dict[str, Any]:
    """Extract YAML frontmatter from SKILL.md content.

    Uses a lightweight key: value parser to avoid pyyaml dependency
    for simple fields, but falls back to yaml for complex structures.
    """
    match = FRONTMATTER_RE.match(content)
    if not match:
        return {}

    fm_text = match.group(1)
    data = _simple_yaml_parse(fm_text)
    return data


def _simple_yaml_parse(text: str) -> Dict[str, Any]:
    """Minimal YAML frontmatter parser for common skill metadata patterns.

    Handles:
      - key: value
      - key: "quoted value"
      - key: [list, items]
      - key: |
        multiline text
      - nested dicts (metadata.hermes.tags etc.)
    """
    # Try full YAML first, fall back to regex-based parsing
    try:
        import yaml
        return yaml.safe_load(text) or {}
    except Exception:
        pass

    result: Dict[str, Any] = {}
    current_key: Optional[str] = None
    current_multiline: List[str] = []
    in_multiline = False
    multiline_indent = 0

    for line in text.split("\n"):
        # Detect multiline literal continuation
        if in_multiline:
            if line.startswith(" ") and len(line) - len(line.lstrip()) >= multiline_indent:
                current_multiline.append(line)
                continue
            else:
                # End of multiline block
                if current_key:
                    val = "\n".join(current_multiline).strip()
                    _set_nested(result, current_key, val)
                in_multiline = False
                current_multiline = []
                current_key = None

        # Skip empty lines
        if not line.strip():
            continue

        # Try to parse as key: value
        kv_match = re.match(r"^(\S[\w\-./]*)\s*:\s*(.*)", line)
        if kv_match:
            key = kv_match.group(1).strip()
            raw_val = kv_match.group(2).strip()

            # Multiline literal start
            if raw_val == "|" or raw_val.startswith("|-"):
                current_key = key
                in_multiline = True
                multiline_indent = len(line) - len(line.lstrip()) + 2
                current_multiline = []
                continue

            # Inline list: [item1, item2]
            if raw_val.startswith("[") and raw_val.endswith("]"):
                items = [x.strip().strip("\"'") for x in raw_val[1:-1].split(",") if x.strip()]
                _set_nested(result, key, items)
                continue

            # Empty value
            if not raw_val:
                _set_nested(result, key, "")
                continue

            # Simple value (strip quotes)
            val = raw_val.strip("\"'")
            _set_nested(result, key, val)
            continue

        # Try to parse as list item under a key: - value
        list_match = re.match(r"^\s*-\s+(.*)", line)
        if list_match:
            item = list_match.group(1).strip("\"'")
            # Find the last set key that could own this list
            if current_key:
                existing = _get_nested(result, current_key, [])
                if isinstance(existing, list):
                    existing.append(item)
                    _set_nested(result, current_key, existing)
            continue

    # Flush any remaining multiline
    if in_multiline and current_key:
        val = "\n".join(current_multiline).strip()
        _set_nested(result, current_key, val)

    return result


def _set_nested(d: Dict, key: str, value: Any) -> None:
    """Set a dot-separated nested key in dict, creating intermediates as needed."""
    parts = key.split(".")
    for part in parts[:-1]:
        if part not in d:
            d[part] = {}
        if not isinstance(d[part], dict):
            d[part] = {}
        d = d[part]
    d[parts[-1]] = value


def _get_nested(d: Dict, key: str, default: Any = None) -> Any:
    """Get a dot-separated nested key from dict."""
    parts = key.split(".")
    for part in parts:
        if not isinstance(d, dict) or part not in d:
            return default
        d = d[part]
    return d


def scan_skills_directory(skills_dir: str) -> List[Dict[str, Any]]:
    """Walk skills directory and parse all SKILL.md files.

    Returns a list of skill dicts with:
      - name (str): skill name from frontmatter or dir name
      - path (str): absolute path to SKILL.md
      - dir (str): absolute path to skill directory
      - category (str): parent dir name (e.g. 'devops', 'toBPost')
      - version (str): from frontmatter
      - status (str): from frontmatter, default 'active'
      - supersedes (list): skills this one replaces
      - superseded_by (str): skill that replaces this one
      - description (str)
      - tags (list)
      - triggers (list)
      - platforms (list)
      - raw_frontmatter (dict): the full parsed frontmatter
      - content_preview (str): first 500 chars of body text
    """
    skills = []
    skills_path = Path(skills_dir)

    if not skills_path.exists():
        logger.error(f"Skills directory not found: {skills_dir}")
        return skills

    for sk_file in skills_path.rglob("SKILL.md"):
        skill_dir = sk_file.parent
        category = skill_dir.parent.name if skill_dir.parent.name != "skills" else ""

        try:
            content = sk_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Cannot read {sk_file}: {e}")
            continue

        fm = parse_frontmatter(content)

        skill_name = fm.get("name") or skill_dir.name
        version = str(fm.get("version", "")) if fm.get("version") else ""
        status = fm.get("status", "active") or "active"

        # Parse supersedes (can be string or list)
        raw_supersedes = fm.get("supersedes", [])
        if isinstance(raw_supersedes, str):
            supersedes_list = [s.strip() for s in raw_supersedes.split(",") if s.strip()]
        elif isinstance(raw_supersedes, list):
            supersedes_list = raw_supersedes
        else:
            supersedes_list = []

        superseded_by = fm.get("superseded_by", "") or ""

        description = fm.get("description", "") or ""

        # Extract tags from metadata.hermes.tags
        tags = []
        metadata = fm.get("metadata", {})
        if isinstance(metadata, dict):
            hermes_meta = metadata.get("hermes", {})
            if isinstance(hermes_meta, dict):
                tags = hermes_meta.get("tags", [])

        # Extract triggers from frontmatter
        triggers_raw = fm.get("triggers", [])
        if isinstance(triggers_raw, str):
            trigger_list = [t.strip() for t in triggers_raw.split("\n") if t.strip()]
        elif isinstance(triggers_raw, list):
            trigger_list = triggers_raw
        else:
            trigger_list = []

        # Also extract triggers embedded in description
        desc_triggers = _extract_triggers_from_description(description)
        all_triggers = list(set(trigger_list + desc_triggers))

        # Platforms
        platforms = fm.get("platforms", [])
        if isinstance(platforms, str):
            platforms = [p.strip() for p in platforms.split(",")]

        # Body text (everything after frontmatter) for keyword analysis
        fm_end = FRONTMATTER_RE.search(content)
        body = ""
        if fm_end:
            body = content[fm_end.end():].strip()

        skill_info = {
            "name": skill_name,
            "path": str(sk_file),
            "dir": str(skill_dir),
            "category": category,
            "version": version,
            "status": status,
            "supersedes": supersedes_list,
            "superseded_by": superseded_by,
            "description": description,
            "tags": tags if isinstance(tags, list) else [],
            "triggers": all_triggers,
            "platforms": platforms,
            "raw_frontmatter": dict(fm),
            "body_preview": body[:500],
            "body": body,
        }
        skills.append(skill_info)

    return skills


def _extract_triggers_from_description(description: str) -> List[str]:
    """Extract trigger keywords from description fields that list them."""
    triggers = []
    # Pattern: "触发词：xxx、yyy、zzz"
    match = re.search(r"触发词[：:]\s*(.+)", description)
    if match:
        raw = match.group(1)
        triggers = [t.strip() for t in re.split(r"[、,，]", raw) if t.strip()]
    return triggers
