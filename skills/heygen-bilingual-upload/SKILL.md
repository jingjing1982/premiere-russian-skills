---
name: heygen-bilingual-upload
description: 结合对应HeyGen导出Excel与最终俄中SRT分配speaker并生成CSV，保留全部正文和时间。 仅讨论或检查时不操作工程。
---

# 生成HeyGen上传CSV

## 用户使用
- **什么时候用：** 视频已上传HeyGen，已下载对应Excel，合并SRT已最终确认时。
- **需要准备：** 每个视频对应的Excel和最终双语SRT；分部提供准确分界；忘记切点时可提供实际导出视频及可用导出记录。
- **一句调用：** `$heygen-bilingual-upload 用这些配套Excel和SRT生成上传CSV，speaker按Excel填写。`
- **完成后检查：** 检查两种声音交接、分部偏移和异常清单；CSV不会自动上传。

## 执行要求
先读[共用流程与时间版本交接](references/workflow.md)和[默认参数](assets/defaults.json)。本技能只完成自己的阶段；不修改原文件，不自动接续其他技能。来源、参数、证据及核验按本次任务记录，不能借用其他用户历史约定。

本次明确记录的参数覆盖值优先于参考文档中的默认数值示例；只接受程序实际支持的参数。
先运行`python scripts/preflight.py`检查离线依赖。脚本路径均相对此技能目录；助手填实际输入路径，用户不必编辑脚本。

完整读取references/operation.md及references/bilingual-srt-to-csv.txt；按references/converter-usage.md使用统一转换器。不需要连接PR。标准交付speaker不得空，notes留空；标签只来自该Excel，不重新编号。一条SRT一行，不改分段、语速、文字和时间。
先核对版本、字段及时间原点；有现成handoff先check，无记录的外部文件按workflow.md核实后登记。不得把“已提供两文件”当成没有冲突的证明。先运行`srt_to_heygen_csv.py 最终.srt --template-xlsx 导出.xlsx --audit-speakers`；跨标签/多容差/中点空档先核查正文与真实讲话归属。不把中点当声纹证明。正文混入两人退回合并阶段；时间偏移或误标只有真实证据才填speaker-review。
另外核对每次短对话交接：时间重排后的整条字幕可能完全落入另一人的Excel时段，程序此时未必报警。优先复用绑定当前来源的合并阶段说话人证据并对照Excel台词；有偏移时检查该对话的全部短轮次，不只检查报警条目。无证据不得按内容猜人；核实后可对未报警条目同样提交speaker-review。
公开交付入口：`python scripts/upload_checked.py 最终.srt 上传.csv --template-xlsx 导出.xlsx --handoff handoff.json --report 生成核验.json`；有复核加--speaker-review 实际复核.json。再另跑同命令加--verify-only，report用新文件名。verified=true、speaker_empty_count=0、无未决跨人问题才交付。原文OK等短句不删不翻译。
分部先读[实际视频分界核对](references/segmented-video.md)，核实精确范围及各部真实起点；使用原始转换器--parts-manifest，经完整覆盖校验，逐份--verify-only。每部登记局部SRT/视频交接记录并核对其文字和时间与源映射完全一致，不能通过填错局部时码“验证”自己。单条跨分界拒绝自动拆字。详见converter-usage.md。


## 任务收尾

开始与交付前遵循[任务目录、预览和收尾](references/task-lifecycle.md)。不重复创建备份、预览或依赖环境；不清理用户已有工程和素材。
