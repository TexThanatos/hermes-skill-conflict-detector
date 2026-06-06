# Hermes Skill Conflict Detector

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

**English | [中文版](README.zh.md)**

> 检测 [Hermes Agent](https://hermes-agent.nousresearch.com/) 技能（Skills）之间的冲突、断裂关系和维护问题。

技能库一多（151+ 个），技能之间必然会互相重叠——同一个平台有不同操作方案、同一个关键词有多个技能响应、废弃技能没人管。这个工具帮你把这些乱麻理清楚。

## 检测项一览

| 检测项 | 严重度 | 发现什么 |
|-------|--------|---------|
| **同名冲突** | 🔴 错误 | 两个技能用了同一个名字 |
| **Supersedes 链条断裂** | 🔴 错误 | A 声明覆盖 B，但 B 没有反向声明 |
| **循环覆盖** | 🔴 错误 | A → B → C → A 死循环 |
| **覆盖不存在的技能** | 🟡 警告 | 声明覆盖一个根本不存在的技能 |
| **反向引用缺失** | 🟡 警告 | B 说被 A 覆盖，但 A 没提 B |
| **废弃无替代** | 🟡 警告 | 标了 deprecated 但没人接盘 |
| **触发词重叠** | 🔵 提示/🟡 警告 | 两个技能覆盖同一关键词（如"闲鱼/publish"）但没声明关系 |
| **缺失元数据** | 🔵 提示 | 缺 version、status、description 或 triggers |
| **正文方法冲突** | 🟡 警告 | 两个技能覆盖同一平台但用完全不同的工具链（需 --deep 模式） |
| **描述相似** | 🔵 提示 | 同分类下 Jaccard 相似度 >50% |

## 快速开始

```bash
# 安装
pip install git+https://github.com/TexThanatos/hermes-skill-conflict-detector.git

# 扫默认技能目录
skill-conflicts

# 扫指定目录
skill-conflicts ~/.hermes/skills

# 深度扫描（分析正文工具链冲突）
skill-conflicts --deep

# JSON 输出
skill-conflicts --format json

# 保存到文件
skill-conflicts -o report.md

# 只看错误和警告
skill-conflicts --severity ERROR,WARNING

# 跳过元数据检查（减少噪音）
skill-conflicts --skip metadata

# 深度模式跳过噪音检查
skill-conflicts --deep --skip metadata
```

## 输出示例

```markdown
# Hermes Skill Conflict Detector Report

## Summary
| Metric | Value |
|--------|-------|
| Total skills scanned | 167 |
| Total issues found | 39 |
| Errors | 0 |
| Warnings | 30 |
| Info | 9 |

### 🟡 WARNING

**'xianyu-publish' and 'xianyu-vr-posting' both target 闲鱼 but use different tool chains**
  - skill_a: xianyu-publish (tools: OpenCLI, CDP)
  - skill_b: xianyu-vr-posting (tools: pyautogui, ScreenClaw)
  - Suggestion: declare supersedes or mark as complementary
```

## 如何处理检测结果

### 🔴 错误
需要立即处理。Supersedes 链条断裂意味着加载两个技能时可能拿到的指令互相矛盾。

**修复示例：**
```yaml
# 在新技能（如 xianyu-publish）里声明：
---
name: xianyu-publish
supersedes:
  - xianyu-automation
---

# 在旧技能（如 xianyu-automation）里声明：
---
name: xianyu-automation
status: deprecated
superseded_by: xianyu-publish
---
```

### 🟡 警告
需要人工确认。最常见的是触发词重叠——两个技能覆盖同一领域，代理可能选错。

### 🔵 提示
属于家务活。补上缺失的元数据字段，让代理更好地理解你的技能。

## 常见问题

### 为什么需要这个工具？
Hermes 把所有技能目录扫出来全部提供给代理。如果两个技能对同一操作给出不同方案（比如一个说"用 OpenCLI"，另一个说"用 ScreenClaw"），代理只能靠猜。通过声明 `supersedes`/`superseded_by` 关系解决。

### 工具会自动修复吗？
不，它只报告问题。你需要手动修改 SKILL.md 文件（或者让 Hermes 代理帮你改）。

### 能在 CI 里跑吗？
可以：
```bash
skill-conflicts --format json --severity ERROR | python -c "import sys,json; print(json.load(sys.stdin)['statistics']['by_severity'].get('ERROR', 0))"
```

## 开发

```bash
git clone https://github.com/TexThanatos/hermes-skill-conflict-detector.git
cd hermes-skill-conflict-detector
pip install -e "."
python -m pytest tests/ -v
```

## 许可

MIT

## 捐赠

如果这个工具帮你省了时间，欢迎请作者喝杯咖啡：

![捐赠收款码](assets/qrcode_donate.jpg)

打工人写轮子不易，感谢支持！
