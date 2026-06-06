---
name: skill-conflict-resolution
version: 0.3.0
description: Runtime conflict detection workflow — cache check, incremental scan, relationship graph. Run before loading domain skills.
status: active
triggers:
  - skill conflict
  - 冲突检测
  - 技能冲突
  - check conflicts
  - 关系图
  - skill graph
  - 增量扫描
---

# Skill Conflict Resolution

**运行时工作流。** 本 skill 定义了 Hermes 代理在加载其他 skill 之前如何检测冲突、使用缓存、以及查看关系图。

## 依赖

- `hermes-skill-conflict-detector` 包已安装在系统 Python 中
- 项目路径: `C:\Users\asd\projects\hermes-skill-conflict-detector`

## 工作流

### 1. 初次运行（全量扫描）

```bash
cd /c/Users/asd/projects/hermes-skill-conflict-detector
python -m skill_conflict_detector.cli ~/.hermes/skills --cache --deep --skip metadata
```

- 对所有 skill 计算 content_hash 并存入 SQLite 缓存
- 执行全量深度扫描
- 结果存入缓存，下次跳过

### 2. 增量扫描（日常运行）

```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --cache --deep --skip metadata
```

- 对比 hash，只扫内容有变化的 skill
- 无变化直接返回上次结果

### 3. 强制重扫

```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --cache --full --deep --skip metadata
```

### 4. 查看关系图

**Mermaid（GitHub 原生渲染）：**
```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --graph
```

**交互式 HTML（浏览器拖拽）：**
```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --graph-html
# 打开 ~/.hermes/skill_relationship_graph.html
```

### 5. 查看指定 skill 的关联关系

```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --cache --related xianyu-publish
```

### 6. 查看缓存状态

```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --cache-stats
```

### 7. 清理缓存

```bash
python -m skill_conflict_detector.cli ~/.hermes/skills --cache-clear
```

## 运行时集成

**加载其他 skill 到自己的流程如下：**

在执行任何涉及 domain skill 的任务前：

1. **检查缓存状态** — 如果从未扫描过 → 执行全量扫描
2. **检查目标 skill 是否变更** — `--related <skill_name>` 查看其关联 skill
3. **如有新增冲突** — 在回复中报告给用户
4. **加载目标 skill** — 正常使用

## 缓存数据库

位置: `~/.hermes/.skill_cache/conflict_cache.db`

| 表 | 用途 |
|----|------|
| `skill_hashes` | skill 名称 → content_hash，用于变更检测 |
| `scan_results` | 扫描历史记录 |
| `skill_relations` | 关系图（supersedes / superseded_by / overlaps） |

## 关系图图例

| 关系 | 线型 | 含义 |
|------|------|------|
| `A --> B` | 实线箭头 | A 覆盖 B（A supersedes B） |
| `A -.-> B` | 虚线箭头 | A 被 B 覆盖（A superseded_by B） |
| `A === B` | 粗线 | 覆盖同一平台但无声明关系（overlaps） |

颜色：🟢 绿色 = active, 🔴 红色 = deprecated, 🟡 黄色 = overlaps

## Pitfalls

- 首次 `--cache` 扫描会比普通扫描慢，因为要写数据库
- `--cache` 不带 `--full` 时，只扫 hash 变化的 skill
- 修改 SKILL.md 后 content_hash 会变，下次增量扫描自动发现
- 关系图的 overlaps 检测依赖于 `analyzer.py` 的 `_PLATFORM_PATTERNS` 配置
