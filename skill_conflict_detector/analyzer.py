"""Conflict detection algorithms for Hermes Agent skills."""

import re
from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from .scanner import _extract_triggers_from_description


# Severity levels
ERROR = "ERROR"
WARNING = "WARNING"
INFO = "INFO"


def detect_naming_conflicts(skills: List[Dict]) -> List[Dict]:
    """Find duplicate skill names across the skills directory.

    Returns issues like:
      ERROR: skill 'xianyu-publish' defined in 2 locations
    """
    issues = []
    by_name: Dict[str, List[Dict]] = defaultdict(list)

    for sk in skills:
        by_name[sk["name"]].append(sk)

    for name, sk_list in by_name.items():
        if len(sk_list) > 1:
            paths = [sk["path"] for sk in sk_list]
            issues.append({
                "type": "naming_conflict",
                "severity": ERROR,
                "message": (
                    f"Skill name '{name}' is defined in {len(sk_list)} locations"
                ),
                "details": {
                    "skill_name": name,
                    "paths": paths,
                },
            })

    return issues


def detect_broken_supersedes_chains(skills: List[Dict]) -> List[Dict]:
    """Check that supersedes/superseded_by declarations are consistent.

    Checks:
      - If A.supersedes = [B], then B.superseded_by must be A
      - If B.superseded_by = A, then A must have B in its supersedes list
      - Circular chains (A → B → C → A)
    """
    issues: List[Dict] = []
    name_map = {sk["name"]: sk for sk in skills}

    # Build the supersedes graph.
    # forward = A.supersedes includes B (A replaces B)
    # backward = B.superseded_by = A (B says it's replaced by A)
    # Cycle detection uses ONLY forward edges. superseded_by is a back-pointer,
    # not a supersedes edge — including it creates false cycles.
    forward: Dict[str, Set[str]] = defaultdict(set)
    backward: Dict[str, Set[str]] = defaultdict(set)

    for sk in skills:
        name = sk["name"]
        for target in sk.get("supersedes", []):
            forward[name].add(target)
            backward[target].add(name)

        if sk.get("superseded_by"):
            backward[sk["superseded_by"]].add(name)
            # NOT adding to forward here — avoid false cycles

    # Check 1: A.supersedes B but B has no superseded_by (broken forward ref)
    for sk in skills:
        name = sk["name"]
        for target in sk.get("supersedes", []):
            target_skill = name_map.get(target)
            if target_skill:
                declared_superseded_by = target_skill.get("superseded_by", "")
                if declared_superseded_by != name:
                    issues.append({
                        "type": "broken_forward_supersedes",
                        "severity": ERROR,
                        "message": (
                            f"'{name}' declares supersedes: [{target}] "
                            f"but '{target}' has superseded_by='{declared_superseded_by}' "
                            f"(expected '{name}')"
                        ),
                        "details": {
                            "source": name,
                            "target": target,
                            "expected_superseded_by": name,
                            "actual_superseded_by": declared_superseded_by or "(empty)",
                            "source_path": sk["path"],
                            "target_path": target_skill.get("path", "(not found)"),
                        },
                    })
            else:
                # Target skill doesn't exist
                issues.append({
                    "type": "supersedes_nonexistent",
                    "severity": WARNING,
                    "message": (
                        f"'{name}' declares supersedes: [{target}] "
                        f"but no skill named '{target}' exists"
                    ),
                    "details": {
                        "source": name,
                        "target": target,
                        "source_path": sk["path"],
                    },
                })

    # Check 2: B.superseded_by = A but A doesn't mention B in its supersedes
    for sk in skills:
        name = sk["name"]
        superseded_by = sk.get("superseded_by", "")
        if superseded_by and superseded_by in name_map:
            parent = name_map[superseded_by]
            if name not in parent.get("supersedes", []):
                issues.append({
                    "type": "broken_backward_supersedes",
                    "severity": WARNING,
                    "message": (
                        f"'{name}' declares superseded_by='{superseded_by}' "
                        f"but '{superseded_by}' does not list '{name}' in its supersedes"
                    ),
                    "details": {
                        "source": name,
                        "expected_parent": superseded_by,
                        "source_path": sk["path"],
                        "parent_path": parent["path"],
                        "parent_supersedes": parent.get("supersedes", []),
                    },
                })

    # Check 3: Detect cycles in the supersedes graph
    cycles = _detect_cycles(forward)
    for cycle in cycles:
        issues.append({
            "type": "supersedes_cycle",
            "severity": ERROR,
            "message": f"Supersedes cycle detected: {' → '.join(cycle + [cycle[0]])}",
            "details": {
                "cycle": cycle,
            },
        })

    return issues


def _detect_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """Detect all simple cycles in a directed graph using DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in graph}
    parent: Dict[str, Optional[str]] = {}
    cycles: List[List[str]] = []

    def dfs(node: str, path: List[str]) -> None:
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in color:
                color[neighbor] = WHITE
            if color[neighbor] == GRAY:
                # Found a cycle
                cycle_start = path.index(neighbor)
                cycle = path[cycle_start:]
                cycles.append(cycle)
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)

        path.pop()
        color[node] = BLACK

    for node in list(graph.keys()):
        if color.get(node, WHITE) == WHITE:
            dfs(node, [])

    return cycles


def detect_orphaned_deprecated(skills: List[Dict]) -> List[Dict]:
    """Find skills marked 'deprecated' that no active skill claims to supersede.

    A deprecated skill should have superseded_by set to an active skill,
    OR there should be at least one active skill that lists it in supersedes.
    """
    issues: List[Dict] = []

    active_names = {sk["name"] for sk in skills if sk.get("status") == "active"}
    deprecated_skills = [sk for sk in skills if sk.get("status") == "deprecated"]

    for sk in deprecated_skills:
        name = sk["name"]
        superseded_by = sk.get("superseded_by", "")

        # Check if any active skill claims to supersede this one
        claimed_by_active = False
        for active_name in active_names:
            for sup in skills:
                if sup["name"] == active_name:
                    if name in sup.get("supersedes", []):
                        claimed_by_active = True
                        superseded_by = active_name
                    break

        if not superseded_by and not claimed_by_active:
            issues.append({
                "type": "orphaned_deprecated",
                "severity": WARNING,
                "message": (
                    f"Skill '{name}' is 'deprecated' but no active skill "
                    f"supersedes it. Either set superseded_by on this skill "
                    f"or add it to an active skill's supersedes list."
                ),
                "details": {
                    "skill_name": name,
                    "path": sk["path"],
                    "version": sk.get("version", ""),
                },
            })

    return issues


def detect_trigger_overlap(skills: List[Dict]) -> List[Dict]:
    """Find skills that share common trigger keywords but have no declared relationship.

    Extracts trigger words from:
      - triggers field
      - tags field
      - description trigger keywords (e.g. "触发词：闲鱼、发布")

    Only meaningful keywords are considered — English stop words and generic
    programming terms are filtered out.

    Skills that overlap on 2+ domain keywords without having any supersedes/superseded_by
    relationship get flagged.
    """
    issues: List[Dict] = []

    # Stop words and generic terms that shouldn't trigger overlap warnings
    _STOP_WORDS = {
        # English stop words
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "has", "have", "been", "some",
        "same", "than", "that", "them", "then", "they", "this", "very",
        "just", "also", "over", "such", "each", "well", "most", "even",
        "like", "into", "back", "from", "with", "your", "will", "what",
        "when", "where", "which", "while", "their", "there", "these",
        "those", "about", "after", "before", "other", "between", "under",
        "without", "because", "through", "another", "whether",
        # Common generic words found in skill descriptions
        "use", "used", "using", "via", "based", "built", "create",
        "works", "working", "support", "supports", "provide", "provides",
        "including", "include", "includes", "need", "needs", "using",
        "check", "follow", "allows", "allow", "lets", "let", "make",
        "made", "set", "configure", "configuration", "setup",
        "get", "list", "show", "find", "search", "view", "run",
        "tool", "tools", "command", "commands", "file", "files",
        "data", "information", "detail", "details", "option", "options",
        "mode", "modes", "type", "types", "format", "formats",
        "result", "results", "output", "input", "process",
        "way", "ways", "method", "methods", "approach", "approaches",
        "feature", "features", "function", "functions",
        "example", "examples", "sample", "samples",
        "category", "categories", "section", "sections",
        "page", "pages", "site", "website", "web",
        "simple", "easy", "quick", "fast", "automatic",
        "through", "whether",
        # Platform/generic tech terms
        "windows", "macos", "linux", "cli", "api", "rest", "http",
        "json", "yaml", "md", "css", "html", "js", "xml", "git",
        "npm", "pip", "docker", "node", "python", "script", "scripts",
        "config", "env", "path", "dir", "directory", "folder",
        "version", "versioning", "runtime",
        "str", "int", "bool", "list", "dict", "set", "tuple",
        # Chinese common words (English equivalents)
        "方式", "方法", "使用", "通过", "可以", "需要", "支持",
        "提供", "包括", "配置", "设置", "参考", "查看", "运行",
        "工具", "命令", "文件", "数据", "信息", "类型", "格式",
        "结果", "输出", "输入", "功能", "示例", "分类", "页面",
        "简单", "快速", "自动",
    }

    # High-value domain keywords that strongly indicate meaningful overlap
    _HIGH_VALUE_KEYWORDS = {
        "闲鱼", "xianyu", "goofish",
        "小红书", "xiaohongshu",
        "发布", "publish", "上架",
        "上传", "upload", "图片", "image",
        "登录", "login", "认证",
        "vr", "xr", "大空间",
        "招商", "加盟", "marketing",
        "微信", "wechat",
        "私信", "消息", "message",
        "cookies", "session", "token",
        "cdp", "debug", "debugging",
        "chrome", "browser", "浏览器",
        "screenclaw", "pyautogui", "自动化",
        "opencli", "部署", "deploy",
        "notion", "obsidian", "笔记",
        "github", "pr", "pull request", "代码审查",
        "docker", "container", "容器",
        "database", "数据库", "sql",
        "monitor", "监控", "监控",
        "backup", "备份", "恢复",
    }

    # Extract all trigger keywords per skill
    skill_triggers: List[Tuple[str, Set[str], Dict]] = []
    for sk in skills:
        triggers = set()

        # From explicit triggers field
        for t in sk.get("triggers", []):
            for word in re.findall(r'[a-zA-Z\u4e00-\u9fff]+', t.lower()):
                if word not in _STOP_WORDS:
                    triggers.add(word)

        # From tags
        for t in sk.get("tags", []):
            word = t.lower().strip()
            if word not in _STOP_WORDS:
                triggers.add(word)

        # From description's explicit "触发词：" section
        desc = sk.get("description", "")
        desc_triggers = _extract_triggers_from_description(desc)
        for t in desc_triggers:
            for word in re.findall(r'[a-zA-Z\u4e00-\u9fff]+', t.lower()):
                if word not in _STOP_WORDS:
                    triggers.add(word)

        skill_triggers.append((sk["name"], triggers, sk))

    # Find pairs with significant overlap
    for i in range(len(skill_triggers)):
        name_a, triggers_a, sk_a = skill_triggers[i]
        for j in range(i + 1, len(skill_triggers)):
            name_b, triggers_b, sk_b = skill_triggers[j]

            # Skip if they already have a declared relationship
            has_relationship = (
                name_a in sk_b.get("supersedes", [])
                or name_b in sk_a.get("supersedes", [])
                or sk_a.get("superseded_by") == name_b
                or sk_b.get("superseded_by") == name_a
            )
            if has_relationship:
                continue

            # Only consider meaningful overlap
            common = triggers_a & triggers_b
            if not common:
                continue

            # Filter out category-name-only overlap (skills in the same category
            # will naturally share the category name — that's not a conflict)
            cat_a = sk_a.get("category", "").lower()
            cat_b = sk_b.get("category", "").lower()
            category_names = set()
            if cat_a:
                category_names.add(cat_a)
            if cat_b:
                category_names.add(cat_b)

            # If all non-stop-word common keywords are just category names, skip
            common_excluding_category = common - category_names
            if not common_excluding_category:
                continue

            # High-value domain keyword overlap (use full common, category doesn't matter)
            high_value_overlap = common & _HIGH_VALUE_KEYWORDS

            # General overlap (excluding category names)
            general_overlap = common_excluding_category - high_value_overlap

            # Don't flag if only overlap is a single category name
            if not high_value_overlap and not general_overlap:
                continue

            # Flag if at least 1 high-value match, or 3+ general matches
            if high_value_overlap or len(general_overlap) >= 3:
                display_list = sorted(high_value_overlap | (general_overlap if len(general_overlap) >= 3 else set()))
                severity = WARNING if high_value_overlap else INFO
                issues.append({
                    "type": "trigger_overlap_without_relationship",
                    "severity": severity,
                    "message": (
                        f"'{name_a}' and '{name_b}' share trigger keywords "
                        f"({' '.join(display_list[:6])}...)"
                        f"{' — consider declaring supersedes relationship' if high_value_overlap else ''}"
                    ),
                    "details": {
                        "skill_a": {"name": name_a, "path": sk_a["path"]},
                        "skill_b": {"name": name_b, "path": sk_b["path"]},
                        "common_triggers": display_list,
                        "high_value_overlap": sorted(high_value_overlap),
                        "suggestion": (
                            f"Consider: if '{name_a}' supersedes '{name_b}', add "
                            f"supersedes: [{name_b}] to '{name_a}' and "
                            f"superseded_by: '{name_a}' to '{name_b}'. "
                            f"If they're complementary, no action needed."
                        ),
                    },
                })

    return issues


def detect_missing_metadata(skills: List[Dict]) -> List[Dict]:
    """Flag skills missing recommended metadata fields.

    Required: name, version
    Recommended: status, description, triggers, platforms
    """
    issues: List[Dict] = []

    for sk in skills:
        name = sk["name"]

        # Missing version
        if not sk.get("version"):
            issues.append({
                "type": "missing_version",
                "severity": INFO,
                "message": (
                    f"Skill '{name}' has no version field in frontmatter. "
                    f"Add 'version: 1.0.0' for tracking."
                ),
                "details": {
                    "skill_name": name,
                    "path": sk["path"],
                    "missing": "version",
                },
            })

        # Missing status (defaults to 'active' but explicit is better)
        raw_fm = sk.get("raw_frontmatter", {})
        if "status" not in raw_fm:
            issues.append({
                "type": "missing_status",
                "severity": INFO,
                "message": (
                    f"Skill '{name}' has no explicit status. "
                    f"Defaults to 'active' but consider adding "
                    f"status: active or status: deprecated."
                ),
                "details": {
                    "skill_name": name,
                    "path": sk["path"],
                    "current_implied": "active",
                },
            })

        # Missing description
        if not sk.get("description", "").strip():
            issues.append({
                "type": "missing_description",
                "severity": WARNING,
                "message": (
                    f"Skill '{name}' has an empty or missing description."
                ),
                "details": {
                    "skill_name": name,
                    "path": sk["path"],
                },
            })

        # Missing triggers
        raw_fm = sk.get("raw_frontmatter", {})
        if "triggers" not in raw_fm:
            issues.append({
                "type": "missing_triggers",
                "severity": INFO,
                "message": (
                    f"Skill '{name}' has no triggers field. "
                    f"Add triggers to help the agent know when to use this skill."
                ),
                "details": {
                    "skill_name": name,
                    "path": sk["path"],
                },
            })

    return issues


def detect_similar_descriptions(skills: List[Dict]) -> List[Dict]:
    """Find skills in the same or adjacent categories with suspiciously overlapping
    descriptions that might indicate duplication."""
    issues: List[Dict] = []

    # Group by category
    by_category: Dict[str, List[Dict]] = defaultdict(list)
    for sk in skills:
        by_category[sk.get("category", "")].append(sk)

    for category, cat_skills in by_category.items():
        if len(cat_skills) < 2:
            continue

        for i in range(len(cat_skills)):
            sk_a = cat_skills[i]
            for j in range(i + 1, len(cat_skills)):
                sk_b = cat_skills[j]

                # Skip if already have relationship
                if (sk_a["name"] in sk_b.get("supersedes", [])
                        or sk_b["name"] in sk_a.get("supersedes", [])
                        or sk_a.get("superseded_by") == sk_b["name"]
                        or sk_b.get("superseded_by") == sk_a["name"]):
                    continue

                desc_a = sk_a.get("description", "").lower()
                desc_b = sk_b.get("description", "").lower()

                # Simple overlap measurement: shared unique words / total unique words
                words_a = set(re.findall(r'[a-zA-Z\u4e00-\u9fff]+', desc_a))
                words_b = set(re.findall(r'[a-zA-Z\u4e00-\u9fff]+', desc_b))

                if not words_a or not words_b:
                    continue

                intersection = words_a & words_b
                union = words_a | words_b

                if not union:
                    continue

                jaccard = len(intersection) / len(union)

                if jaccard > 0.5:
                    issues.append({
                        "type": "similar_description",
                        "severity": INFO,
                        "message": (
                            f"'{sk_a['name']}' and '{sk_b['name']}' in category "
                            f"'{category}' have descriptively similar content "
                            f"(Jaccard similarity: {jaccard:.1%}). "
                            f"Consider if one supersedes the other."
                        ),
                        "details": {
                            "skill_a": {"name": sk_a["name"], "path": sk_a["path"]},
                            "skill_b": {"name": sk_b["name"], "path": sk_b["path"]},
                            "category": category,
                            "jaccard_similarity": round(jaccard, 3),
                            "common_words": sorted(intersection),
                        },
                    })

    return issues
