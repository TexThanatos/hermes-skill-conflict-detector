# Hermes Skill Conflict Detector

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**[中文版](README.zh.md) | English**

**Detect conflicts, broken relationships, and maintenance issues between [Hermes Agent](https://hermes-agent.nousresearch.com/) skills.**

As your skill collection grows (151+ and counting), skills inevitably overlap in domain, trigger keywords, and purpose. This tool helps you keep them organized by surfacing:

## Detection Checks

| Check | Severity | What It Finds |
|-------|----------|---------------|
| **Naming Conflicts** | 🔴 ERROR | Two skills with the same name in different locations |
| **Broken Supersedes Chains** | 🔴 ERROR | `A.supersedes: [B]` but `B.superseded_by` doesn't point back to `A` |
| **Supersedes Cycles** | 🔴 ERROR | Circular dependency: A → B → C → A |
| **Supersedes Nonexistent** | 🟡 WARNING | Skill claims to supersede one that doesn't exist |
| **Broken Backward Ref** | 🟡 WARNING | `B.superseded_by: A` but A doesn't list B in its supersedes |
| **Orphaned Deprecated** | 🟡 WARNING | Skill is `deprecated` but no active skill replaces it |
| **Trigger Overlap** | 🔵 INFO/🟡 WARNING | Two skills share trigger keywords (e.g. both cover "闲鱼/publish") with no declared relationship |
| **Missing Metadata** | 🔵 INFO | Skill missing `version`, `status`, `description`, or `triggers` |
| **Similar Descriptions** | 🔵 INFO | Skills in the same category with >50% Jaccard-similar descriptions |

## Quick Start

```bash
# Install
pip install hermes-skill-conflict-detector

# Run against default skills directory
skill-conflicts

# Specify a custom skills directory
skill-conflicts ~/.hermes/skills

# JSON output
skill-conflicts --format json

# Save to file
skill-conflicts -o report.md

# Filter by severity
skill-conflicts --severity ERROR,WARNING

# Skip noisy checks
skill-conflicts --skip triggers,metadata

# Get full verbose output
skill-conflicts -v
```

## Output Example

```markdown
# Hermes Skill Conflict Detector Report

**Generated:** 2026-06-06 15:30:00

## Summary
| Metric | Value |
|--------|-------|
| Total skills scanned | 151 |
| Total issues found | 7 |
| Errors | 2 |
| Warnings | 3 |
| Info | 2 |

## Issues

### 🔴 ERROR (2)

**'xianyu-publish' declares supersedes: [xianyu-automation] but 'xianyu-automation' has superseded_by='' (expected 'xianyu-publish')**
  - Source: `xianyu-publish`
  - Target: `xianyu-automation`

### 🟡 WARNING (3)

**Skill 'screenclaw-web-form-automation' has no explicit status. Defaults to 'active' but consider adding status: active or status: deprecated.**
  - Path: `~/.../screenclaw-web-form-automation/SKILL.md`
```

## What the Detection Reports Mean

### For `ERROR` items
These need immediate attention. Broken supersedes chains mean the agent may load conflicting instructions for the same task.

**Fix example:**
```yaml
# In the superseding skill (e.g. xianyu-publish):
---
name: xianyu-publish
supersedes:
  - xianyu-automation      # Declare: this skill replaces the old one
---

# In the deprecated skill (e.g. xianyu-automation):
---
name: xianyu-automation
status: deprecated
superseded_by: xianyu-publish   # Declare: I've been replaced by this
---
```

### For `WARNING` items
Should be reviewed. Trigger overlap without relationship is the most common one — it means two skills cover the same domain and the agent might pick the wrong one.

### For `INFO` items
Housekeeping. Add missing metadata fields to help the agent understand your skills better.

## FAQ

### Why do I need this?
Hermes loads skills by scanning `~/.hermes/skills/` and presents them all to the agent. If two skills say different things about the same operation (e.g. `xianyu-publish` says "use OpenCLI" while `screenclaw-web-form-automation` says "use ScreenClaw"), the agent has to guess which one is current. Declaring `supersedes` relationships solves this.

### Does this fix the conflicts?
No — it reports them. You need to update the SKILL.md files yourself (or let your Hermes agent do it).

### Can I run this in CI?
Yes:
```bash
skill-conflicts --format json --severity ERROR | jq '.statistics.by_severity.ERROR'
```

## Development

```bash
git clone https://github.com/TexThanatos/hermes-skill-conflict-detector.git
cd hermes-skill-conflict-detector
pip install -e ".[dev]"

# Run against your local skills
skill-conflicts ~/.hermes/skills -v

# Run tests
python -m pytest tests/
```

## License

MIT

## Donate

If this tool saved you time and you'd like to buy the author a coffee:

![Donate QR Code](assets/qrcode_donate.jpg)

Your support keeps the skills conflict-free!
