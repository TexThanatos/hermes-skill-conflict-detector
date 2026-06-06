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
    """Find duplicate skill names across the skills directory."""
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
                "details": {"skill_name": name, "paths": paths},
            })

    return issues


def detect_broken_supersedes_chains(skills: List[Dict]) -> List[Dict]:
    """Check that supersedes/superseded_by declarations are consistent.

    Checks:
      - If A.supersedes = [B], then B.superseded_by must be A
      - If B.superseded_by = A, then A must have B in its supersedes list
      - Circular chains (A -> B -> C -> A)
    """
    issues: List[Dict] = []
    name_map = {sk["name"]: sk for sk in skills}

    # Build graph. Cycle detection uses ONLY forward edges (supersedes).
    # superseded_by is a back-pointer, not a supersedes edge.
    forward: Dict[str, Set[str]] = defaultdict(set)
    backward: Dict[str, Set[str]] = defaultdict(set)

    for sk in skills:
        name = sk["name"]
        for target in sk.get("supersedes", []):
            forward[name].add(target)
            backward[target].add(name)

        if sk.get("superseded_by"):
            backward[sk["superseded_by"]].add(name)

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
                            "source": name, "target": target,
                            "expected_superseded_by": name,
                            "actual_superseded_by": declared_superseded_by or "(empty)",
                            "source_path": sk["path"],
                            "target_path": target_skill.get("path", "(not found)"),
                        },
                    })
            else:
                issues.append({
                    "type": "supersedes_nonexistent",
                    "severity": WARNING,
                    "message": (
                        f"'{name}' declares supersedes: [{target}] "
                        f"but no skill named '{target}' exists"
                    ),
                    "details": {
                        "source": name, "target": target, "source_path": sk["path"],
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
                        "source": name, "expected_parent": superseded_by,
                        "source_path": sk["path"], "parent_path": parent["path"],
                        "parent_supersedes": parent.get("supersedes", []),
                    },
                })

    # Check 3: Detect cycles in the forward graph only
    cycles = _detect_cycles(forward)
    for cycle in cycles:
        issues.append({
            "type": "supersedes_cycle",
            "severity": ERROR,
            "message": f"Supersedes cycle detected: {' -> '.join(cycle + [cycle[0]])}",
            "details": {"cycle": cycle},
        })

    return issues


def _detect_cycles(graph: Dict[str, Set[str]]) -> List[List[str]]:
    """Detect all simple cycles in a directed graph using DFS."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {node: WHITE for node in graph}
    cycles: List[List[str]] = []

    def dfs(node: str, path: List[str]) -> None:
        color[node] = GRAY
        path.append(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in color:
                color[neighbor] = WHITE
            if color[neighbor] == GRAY:
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
    """Find skills marked 'deprecated' that no active skill claims to supersede."""
    issues: List[Dict] = []

    active_names = {sk["name"] for sk in skills if sk.get("status") == "active"}
    deprecated_skills = [sk for sk in skills if sk.get("status") == "deprecated"]

    for sk in deprecated_skills:
        name = sk["name"]
        superseded_by = sk.get("superseded_by", "")

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
                    "skill_name": name, "path": sk["path"],
                    "version": sk.get("version", ""),
                },
            })

    return issues


def detect_trigger_overlap(skills: List[Dict]) -> List[Dict]:
    """Find skills sharing trigger keywords but lacking a declared relationship."""
    issues: List[Dict] = []

    _STOP_WORDS = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can", "had",
        "her", "was", "one", "our", "out", "has", "have", "been", "some",
        "same", "than", "that", "them", "then", "they", "this", "very",
        "just", "also", "over", "such", "each", "well", "most", "even",
        "like", "into", "back", "from", "with", "your", "will", "what",
        "when", "where", "which", "while", "their", "there", "these",
        "those", "about", "after", "before", "other", "between", "under",
        "without", "because", "through", "another", "whether",
        "use", "used", "using", "via", "based", "built", "create",
        "works", "working", "support", "supports", "provide", "provides",
        "including", "include", "includes", "need", "needs",
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
        "through", "whether", "on", "in", "to", "of", "it", "as",
        "is", "at", "by", "be", "if", "no", "an", "or", "do", "up",
        "any", "how", "new", "own", "two", "top", "key", "off", "end",
        "way", "see", "may", "now", "old", "per",
        "windows", "macos", "linux", "cli", "api", "rest", "http",
        "json", "yaml", "md", "css", "html", "js", "xml", "git",
        "npm", "pip", "docker", "node", "python", "script", "scripts",
        "config", "env", "path", "dir", "directory", "folder",
        "version", "versioning", "runtime",
        "str", "int", "bool", "list", "dict", "set", "tuple",
        "方式", "方法", "使用", "通过", "可以", "需要", "支持",
        "提供", "包括", "配置", "设置", "参考", "查看", "运行",
        "工具", "命令", "文件", "数据", "信息", "类型", "格式",
        "结果", "输出", "输入", "功能", "示例", "分类", "页面",
        "简单", "快速", "自动",
    }

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
        "monitor", "监控",
        "backup", "备份", "恢复",
    }

    skill_triggers: List[Tuple[str, Set[str], Dict]] = []
    for sk in skills:
        triggers = set()

        for t in sk.get("triggers", []):
            for word in re.findall(r'[a-zA-Z\u4e00-\u9fff]+', t.lower()):
                if word not in _STOP_WORDS:
                    triggers.add(word)

        for t in sk.get("tags", []):
            word = t.lower().strip()
            if word not in _STOP_WORDS:
                triggers.add(word)

        desc = sk.get("description", "")
        for t in _extract_triggers_from_description(desc):
            for word in re.findall(r'[a-zA-Z\u4e00-\u9fff]+', t.lower()):
                if word not in _STOP_WORDS:
                    triggers.add(word)

        skill_triggers.append((sk["name"], triggers, sk))

    for i in range(len(skill_triggers)):
        name_a, triggers_a, sk_a = skill_triggers[i]
        for j in range(i + 1, len(skill_triggers)):
            name_b, triggers_b, sk_b = skill_triggers[j]

            if (name_a in sk_b.get("supersedes", [])
                    or name_b in sk_a.get("supersedes", [])
                    or sk_a.get("superseded_by") == name_b
                    or sk_b.get("superseded_by") == name_a):
                continue

            common = triggers_a & triggers_b
            if not common:
                continue

            cat_a = sk_a.get("category", "").lower()
            cat_b = sk_b.get("category", "").lower()
            category_names = set()
            if cat_a: category_names.add(cat_a)
            if cat_b: category_names.add(cat_b)

            common_excluding_category = common - category_names
            if not common_excluding_category:
                continue

            high_value_overlap = common & _HIGH_VALUE_KEYWORDS
            general_overlap = common_excluding_category - high_value_overlap

            if not high_value_overlap and not general_overlap:
                continue

            if high_value_overlap or len(general_overlap) >= 3:
                display = sorted(high_value_overlap | (general_overlap if len(general_overlap) >= 3 else set()))
                severity = WARNING if high_value_overlap else INFO
                issues.append({
                    "type": "trigger_overlap_without_relationship",
                    "severity": severity,
                    "message": (
                        f"'{name_a}' and '{name_b}' share trigger keywords "
                        f"({' '.join(display[:6])}...)"
                        f"{' -- consider declaring supersedes relationship' if high_value_overlap else ''}"
                    ),
                    "details": {
                        "skill_a": {"name": name_a, "path": sk_a["path"]},
                        "skill_b": {"name": name_b, "path": sk_b["path"]},
                        "common_triggers": display,
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
    """Flag skills missing recommended metadata fields."""
    issues: List[Dict] = []

    for sk in skills:
        name = sk["name"]

        if not sk.get("version"):
            issues.append({
                "type": "missing_version",
                "severity": INFO,
                "message": f"Skill '{name}' has no version field.",
                "details": {"skill_name": name, "path": sk["path"], "missing": "version"},
            })

        raw_fm = sk.get("raw_frontmatter", {})
        if "status" not in raw_fm:
            issues.append({
                "type": "missing_status",
                "severity": INFO,
                "message": f"Skill '{name}' has no explicit status (defaults to 'active').",
                "details": {"skill_name": name, "path": sk["path"], "current_implied": "active"},
            })

        if not sk.get("description", "").strip():
            issues.append({
                "type": "missing_description",
                "severity": WARNING,
                "message": f"Skill '{name}' has an empty description.",
                "details": {"skill_name": name, "path": sk["path"]},
            })

        if "triggers" not in raw_fm:
            issues.append({
                "type": "missing_triggers",
                "severity": INFO,
                "message": f"Skill '{name}' has no triggers field.",
                "details": {"skill_name": name, "path": sk["path"]},
            })

    return issues


def detect_similar_descriptions(skills: List[Dict]) -> List[Dict]:
    """Find skills in the same category with suspiciously overlapping descriptions."""
    issues: List[Dict] = []

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

                if (sk_a["name"] in sk_b.get("supersedes", [])
                        or sk_b["name"] in sk_a.get("supersedes", [])
                        or sk_a.get("superseded_by") == sk_b["name"]
                        or sk_b.get("superseded_by") == sk_a["name"]):
                    continue

                desc_a = sk_a.get("description", "").lower()
                desc_b = sk_b.get("description", "").lower()

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
                            f"(Jaccard similarity: {jaccard:.1%})."
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


# ── Body content deep analysis ──────────────────────────────────────────

_TOOL_PATTERNS = {
    "OpenCLI":     r'opencli',
    "pyautogui":   r'pyautogui',
    "ScreenClaw":  r'screenclaw|ScreenClaw',
    "pywinauto":   r'pywinauto',
    "CDP":         r'remote-debugging-port|chrome.?devtools|CDP|cdp',
    "Playwright":  r'playwright',
    "pyppeteer":   r'pyppeteer',
    "WebSocket":   r'websocket-client|websocket\.create',
    "PIL":         r'PIL|pillow',
    "pyperclip":   r'pyperclip',
    "Camofox":     r'camofox|Camofox',
    "gh CLI":      r'gh\s',
    "git":         r'\bgit\b',
    "Docker":      r'docker',
    "pytest":      r'pytest',
    "requests":    r'requests\.',
    "curl":        r'\bcurl\b',
}

_PLATFORM_PATTERNS = {
    "闲鱼":        r'闲鱼|goofish|xianyu',
    "小红书":      r'小红书|xiaohongshu|creator\.xiaohongshu',
    "GitHub":      r'github\.com',
    "微信":        r'微信|wechat',
    "飞书":        r'飞书|feishu|lark',
    "Discord":     r'discord',
    "Telegram":    r'telegram',
}

_METHOD_KEYWORDS = {
    "desktop_click":  r'pyautogui\.click|pywinauto.*click|桌面点击|物理点击',
    "cdp_command":    r'cmd\(|Runtime\.evaluate|CDP.*命令|opencli.*eval',
    "clipboard":      r'pyperclip\.copy|剪贴板|Ctrl\+V|ctrl.*v',
    "file_upload":    r'uploadFile|setFileInput|DOM\.setFileInputFiles|文件上传|上传图片',
    "screenshot":     r'screenshot|截图|vision.*分析',
    "api_call":       r'requests\.|curl\s|API.*调用',
    "eval_js":        r'\beval\(|opencli.*eval|document\.querySelector',
    "form_fill":      r'typewrite|write\(|Input\.insertText|表单填写',
    "iframe_op":      r'--frame\s|iframe|跨域',
    "login_flow":     r'登录|login|扫码.*验证|人脸.*验证|密码登录',
    "file_dialog":    r'文件对话框|文件选择|打开.*对话框',
    "pixel_match":    r'像素.*定位|numpy.*array|像素.*分析|红色.*掩码',
}


def extract_body_profile(body: str) -> Dict:
    """Extract a structured profile from a skill's body text.

    Returns dict with sets: tools, platforms, methods.
    """
    body_lower = body.lower()
    tools = set()
    platforms = set()
    methods = set()

    for name, pattern in _TOOL_PATTERNS.items():
        if re.search(pattern, body_lower):
            tools.add(name)

    for name, pattern in _PLATFORM_PATTERNS.items():
        if re.search(pattern, body_lower):
            platforms.add(name)

    for name, pattern in _METHOD_KEYWORDS.items():
        if re.search(pattern, body_lower):
            methods.add(name)

    return {"tools": tools, "platforms": platforms, "methods": methods}


def detect_body_conflicts_deep(skills: List[Dict]) -> List[Dict]:
    """Scan skill body content for method/tool chain conflicts.

    For skills sharing a target platform but using fundamentally
    different tool chains or operation methods, flag them as conflicting.
    """
    issues: List[Dict] = []

    profiles = {}
    for sk in skills:
        body = sk.get("body", "")
        if not body:
            continue
        profiles[sk["name"]] = extract_body_profile(body)

    names = list(profiles.keys())
    for i in range(len(names)):
        name_a = names[i]
        prof_a = profiles[name_a]
        for j in range(i + 1, len(names)):
            name_b = names[j]
            prof_b = profiles[name_b]

            sk_a = next(sk for sk in skills if sk["name"] == name_a)
            sk_b = next(sk for sk in skills if sk["name"] == name_b)

            if (name_a in sk_b.get("supersedes", [])
                    or name_b in sk_a.get("supersedes", [])
                    or sk_a.get("superseded_by") == name_b
                    or sk_b.get("superseded_by") == name_a):
                continue

            shared_platforms = prof_a["platforms"] & prof_b["platforms"]
            if not shared_platforms:
                continue

            # Filter noise: "GitHub" mentioned in passing doesn't count
            # unless both skills are actually in the github category
            cat_a = sk_a.get("category", "").lower()
            cat_b = sk_b.get("category", "").lower()
            platform_github = {"GitHub"}
            if shared_platforms == platform_github and "github" not in (cat_a + cat_b):
                continue

            shared_tools = prof_a["tools"] & prof_b["tools"]
            all_tools = prof_a["tools"] | prof_b["tools"]

            tool_conflict = False
            if shared_platforms and len(all_tools) >= 2:
                # Different tool chains for same platform
                if not shared_tools and prof_a["tools"] and prof_b["tools"]:
                    tool_conflict = True
                # Method-level conflict: mostly disjoint approaches
                elif shared_tools and prof_a["methods"] and prof_b["methods"]:
                    only_a = prof_a["methods"] - prof_b["methods"]
                    only_b = prof_b["methods"] - prof_a["methods"]
                    if only_a and only_b:
                        complementary = prof_a["methods"] & prof_b["methods"]
                        if len(complementary) <= len(only_a | only_b) * 0.3:
                            tool_conflict = True

            if tool_conflict:
                issues.append({
                    "type": "body_method_conflict",
                    "severity": WARNING,
                    "message": (
                        f"'{name_a}' and '{name_b}' both target "
                        f"{', '.join(sorted(shared_platforms))} "
                        f"but use different tool chains"
                    ),
                    "details": {
                        "shared_platforms": sorted(shared_platforms),
                        "skill_a": {
                            "name": name_a,
                            "path": sk_a["path"],
                            "tools": sorted(prof_a["tools"]),
                            "methods": sorted(prof_a["methods"]),
                            "unique_tools": sorted(prof_a["tools"] - prof_b["tools"]),
                        },
                        "skill_b": {
                            "name": name_b,
                            "path": sk_b["path"],
                            "tools": sorted(prof_b["tools"]),
                            "methods": sorted(prof_b["methods"]),
                            "unique_tools": sorted(prof_b["tools"] - prof_a["tools"]),
                        },
                        "suggestion": (
                            f"These skills cover the same platform with different approaches. "
                            f"Add 'supersedes: [{name_b}]' to '{name_a}' and "
                            f"'superseded_by: {name_a}' to '{name_b}' if one replaces the other."
                        ),
                    },
                })

    return issues
