---
name: ru-srt-merge-by-gaps
description: 按字幕间隙将已有俄中字幕合并并按红色手势锚点规划位置；同一连续区间内部首尾相接。 仅讨论或检查时不操作工程。
---

# 按字幕间隙合并与手势对齐

## 用户使用
- **什么时候用：** 已有俄中字幕，字幕间隙确实要作为分界时。
- **需要准备：** 当前工程和序列；已有俄中字幕、已审核红点。
- **一句调用：** `$ru-srt-merge-by-gaps 按字幕间隙合并当前序列并对齐红点。`
- **完成后检查：** 逐点检查预计对齐、区间衔接和冲突；尚未验证实际俄语音频。

## 执行要求
先读[共用流程与时间版本交接](references/workflow.md)和[默认参数](assets/defaults.json)。本技能只完成自己的阶段；不修改原文件，不自动接续其他技能。来源、参数、证据及核验按本次任务记录，不能借用其他用户历史约定。
涉及PR时先读[连接与能力检查](references/premiere-connection.md)。
本次明确记录的参数覆盖值优先于参考文档中的默认数值示例；只接受程序实际支持的参数。
先运行`python scripts/preflight.py`检查离线依赖。脚本路径均相对此技能目录；助手填实际输入路径，用户不必编辑脚本。

读取references/operation.md、references/alignment.md及references/speaker-mode.md中的说话人证据格式。仅执行间隙模式：任何正字幕间隙均划开大区间，换人同样强制分开；每组源跨度及计算时长均≤默认90秒。区间内多组联合定位、严格零间隙；一个锚点组固定时其前段倒排、后段接排。多锚点可在自然cue边界合理拆组，不能借拆组制造空隙。不可同时满足时交冲突报告，不暗中移动红点、加速或改字。
先独立建立源cue说话轮次与证据，核查每次交接及短句；不把观众镜头当换人。合并仅连接整cue，原换行转空格，正文其他字符不变。俄文读法展开仅供计音节，数字/缩写未知读法不得算零。
以extract_saved_captions输出作为独立来源；计划绑定source_snapshot_sha256，文字不能手工重写。调用`python scripts/merge_checked.py source.json plan.json 新输出目录 --mode gaps`。计划格式见references/alignment.md；speaker_review必需，mode只能gaps或省略，max_duration_ms可明确覆盖默认值。任何同人或跨人重叠、负起点或不可能排布都先输出具体冲突，不导出SRT；nonoverlap.py在导出前和回读后硬检查。写handoff为merged-review。


## 任务收尾

开始与交付前遵循[任务目录、预览和收尾](references/task-lifecycle.md)。不重复创建备份、预览或依赖环境；不清理用户已有工程和素材。
