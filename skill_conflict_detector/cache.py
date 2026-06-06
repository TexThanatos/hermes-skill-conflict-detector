"""Skill cache with SQLite — stores skill content hashes and scan results.

Enables incremental scanning: only re-analyze skills whose content has changed.
"""

import hashlib
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


CACHE_DIR = Path.home() / ".hermes" / ".skill_cache"
CACHE_DB = CACHE_DIR / "conflict_cache.db"


def _ensure_db():
    """Create cache directory and tables if they don't exist."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(CACHE_DB))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_hashes (
            skill_name TEXT PRIMARY KEY,
            skill_path TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            last_scanned REAL NOT NULL,
            body_hash TEXT NOT NULL DEFAULT ''
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS scan_results (
            scan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_time REAL NOT NULL,
            scan_type TEXT NOT NULL DEFAULT 'full',
            changed_skills TEXT NOT NULL DEFAULT '[]',
            issues TEXT NOT NULL DEFAULT '[]',
            stats TEXT NOT NULL DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS skill_relations (
            skill_a TEXT NOT NULL,
            relation TEXT NOT NULL,
            skill_b TEXT NOT NULL,
            PRIMARY KEY (skill_a, relation, skill_b)
        )
    """)
    conn.commit()
    return conn


def compute_skill_hash(skill: Dict) -> Tuple[str, str]:
    """Compute hash of a skill's frontmatter + body content.

    Returns (full_hash, body_hash).
    """
    content = skill.get("body", "")
    frontmatter = json.dumps(skill.get("raw_frontmatter", {}), sort_keys=True)
    full = hashlib.sha256((frontmatter + content).encode()).hexdigest()
    body = hashlib.sha256(content.encode()).hexdigest()
    return full, body


def get_cached_hashes() -> Dict[str, Dict]:
    """Return dict of cached skill hashes: {name: {hash, body_hash, path}}."""
    conn = _ensure_db()
    rows = conn.execute(
        "SELECT skill_name, content_hash, body_hash, skill_path FROM skill_hashes"
    ).fetchall()
    conn.close()
    return {
        r[0]: {"hash": r[1], "body_hash": r[2], "path": r[3]}
        for r in rows
    }


def update_skill_hash(skill: Dict, full_hash: str, body_hash: str):
    """Insert or update a skill's cache entry."""
    conn = _ensure_db()
    conn.execute(
        """INSERT OR REPLACE INTO skill_hashes
           (skill_name, skill_path, content_hash, body_hash, last_scanned)
           VALUES (?, ?, ?, ?, ?)""",
        (skill["name"], skill["path"], full_hash, body_hash, time.time()),
    )
    conn.commit()
    conn.close()


def find_changed_skills(skills: List[Dict]) -> Tuple[List[Dict], List[str]]:
    """Compare skills against cache and return (changed_skills, changed_names).

    First run (empty cache) returns all skills as changed.
    """
    cached = get_cached_hashes()
    changed = []
    changed_names = []

    for sk in skills:
        full_hash, body_hash = compute_skill_hash(sk)
        cached_entry = cached.get(sk["name"])

        if cached_entry is None:
            # New skill — never scanned
            changed.append(sk)
            changed_names.append(sk["name"])
        elif cached_entry["hash"] != full_hash:
            # Content changed
            changed.append(sk)
            changed_names.append(sk["name"])

    return changed, changed_names


def save_scan_result(
    changed_skills: List[str],
    issues: List[Dict],
    stats: Dict[str, Any],
    scan_type: str = "incremental",
):
    """Save a scan result to the cache."""
    conn = _ensure_db()
    conn.execute(
        """INSERT INTO scan_results
           (scan_time, scan_type, changed_skills, issues, stats)
           VALUES (?, ?, ?, ?, ?)""",
        (time.time(), scan_type, json.dumps(changed_skills),
         json.dumps(issues, ensure_ascii=False), json.dumps(stats)),
    )
    conn.commit()
    conn.close()


def get_last_scan() -> Optional[Dict]:
    """Get the most recent scan result."""
    conn = _ensure_db()
    row = conn.execute(
        "SELECT scan_id, scan_time, scan_type, changed_skills, issues, stats "
        "FROM scan_results ORDER BY scan_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        return {
            "scan_id": row[0],
            "scan_time": row[1],
            "scan_type": row[2],
            "changed_skills": json.loads(row[3]),
            "issues": json.loads(row[4]),
            "stats": json.loads(row[5]),
        }
    return None


def update_skill_relations(skills: List[Dict]):
    """Build and persist the skill relationship graph.

    Relations tracked:
      - supersedes: A.supersedes = [B]
      - superseded_by: A.superseded_by = B
      - overlaps: A shares platform/domain with B (from body analysis)
      - complementary: tagged as complementary (manual)
    """
    conn = _ensure_db()
    conn.execute("DELETE FROM skill_relations")

    # Direct relationship declarations
    for sk in skills:
        name = sk["name"]
        for target in sk.get("supersedes", []):
            conn.execute(
                "INSERT OR REPLACE INTO skill_relations VALUES (?, 'supersedes', ?)",
                (name, target),
            )
        if sk.get("superseded_by"):
            conn.execute(
                "INSERT OR REPLACE INTO skill_relations VALUES (?, 'superseded_by', ?)",
                (name, sk["superseded_by"]),
            )

    conn.commit()
    conn.close()


def get_related_skills(skill_name: str) -> Dict[str, List[str]]:
    """Get all skills related to a given skill.

    Returns: {supersedes: [...], superseded_by: [...], overlaps: [...]}
    """
    conn = _ensure_db()
    rows = conn.execute(
        "SELECT skill_a, relation, skill_b FROM skill_relations "
        "WHERE skill_a = ? OR skill_b = ?",
        (skill_name, skill_name),
    ).fetchall()
    conn.close()

    result = {"supersedes": [], "superseded_by": [], "overlaps": []}
    for a, rel, b in rows:
        if rel == "supersedes":
            if a == skill_name:
                result["supersedes"].append(b)
        elif rel == "superseded_by":
            result["superseded_by"].append(a if b == skill_name else b)
        elif rel == "overlaps":
            other = b if a == skill_name else a
            result["overlaps"].append(other)
    return result


def clear_cache():
    """Remove the entire cache database."""
    if CACHE_DB.exists():
        CACHE_DB.unlink()
        return True
    return False


def cache_stats() -> Dict:
    """Return cache statistics."""
    conn = _ensure_db()
    skill_count = conn.execute("SELECT COUNT(*) FROM skill_hashes").fetchone()[0]
    scan_count = conn.execute("SELECT COUNT(*) FROM scan_results").fetchone()[0]
    rel_count = conn.execute("SELECT COUNT(*) FROM skill_relations").fetchone()[0]
    last_scan = conn.execute(
        "SELECT scan_time FROM scan_results ORDER BY scan_id DESC LIMIT 1"
    ).fetchone()
    conn.close()
    return {
        "cached_skills": skill_count,
        "scan_history": scan_count,
        "relations": rel_count,
        "last_scan": last_scan[0] if last_scan else None,
    }
