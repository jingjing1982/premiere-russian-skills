---
name: ru-srt-merge-by-speaker
description: 无交替口译时按真实说话轮次合并俄中字幕，尽量少切口，每小段首个手势红点优先。 仅讨论或检查时不操作工程。
---

# 按说话轮次合并与手势对齐

## 用户使用
- **什么时候用：** 没有交替口译，希望按讲话人区分并减少切口时。
- **需要准备：** 当前工程和序列；已有俄中字幕、已审核红点。
- **一句调用：** `$ru-srt-merge-by-speaker 演讲和问答没有交替口译，按说话轮次合并并对齐首个红点。`
- **完成后检查：** 确认每次换人独立、首锚位置及需要人工处理的接缝。

## 执行要求
先读[共用流程与时间版本交接](references/workflow.md)和[默认参数](assets/defaults.json)。本技能只完成自己的阶段；不修改原文件，不自动接续其他技能。来源、参数、证据及核验按本次任务记录，不能借用其他用户历史约定。
涉及PR时先读[连接与能力检查](references/premiere-connection.md)。
本次明确记录的参数覆盖值优先于参考文档中的默认数值示例；只接受程序实际支持的参数。
先运行`python scripts/preflight.py`检查离线依赖。脚本路径均相对此技能目录；助手填实际输入路径，用户不必编辑脚本。

读取references/operation.md和references/speaker-mode.md。仅执行说话轮次模式：自然字幕间隙不自动分大段；每次真实换人必须分开，包括短回应、主持插话、致谢。镜头切换/引述别人说话不等于真实换人。
每条源跨度和规划时长均≤默认90秒；轮次内尽量少分，完整句意、经名和引文作为分界复核依据。每小段首个红点优先，次锚只报告，不为次锚新增切口；首锚前无锚段倒排、其后无锚段接排。只有结尾致谢锚点时，按实际俄文谢词开始或词尾的位置倒排，不机械以段尾对红点。
独立建立源cue归属表和交接证据，未确认短句不并入其他轮次。计划格式及speaker_review见references/speaker-mode.md。调用`python scripts/merge_checked.py source.json plan.json 新输出目录 --mode speaker`，plan.mode=speaker_first_anchor，source_snapshot_sha256绑定实际独立提取JSON。max_duration_ms可明确覆盖默认值。
保留各首锚定位；整轮无锚从原末端倒排，同轮次可移动段首尾相接。必要时只整体移动无锚段，保持时长、顺序和文字。整份SRT禁止重叠，导出前与回读后由nonoverlap.py校验；固定边界容量不足只交冲突报告。正空隙、超出源轮次边界及次锚偏差逐处报告。负起点、未决混说不导出。不擅自调整视频或顺延锚点组。写handoff为merged-review。


## 任务收尾

开始与交付前遵循[任务目录、预览和收尾](references/task-lifecycle.md)。不重复创建备份、预览或依赖环境；不清理用户已有工程和素材。
