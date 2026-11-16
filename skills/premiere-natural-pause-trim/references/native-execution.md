# 原生剪辑队列：准备、执行、恢复

仅适用于premiere-connection.md描述的简单结构。计算器不会理解声音，必须先按所选技能确定并审阅删除清单。清单JSON为{"cuts":[[起帧,止帧]],"protected":[],"review_reference":"实际审阅报告及范围"}，使用整数帧、半开区间。自然停顿还须保护有意义动作及实际有效声音；固定长空白技能按长度规则，不声称只删静音。

1. 只读核实源与预览当前保存内容。记录轨道target/lock/sync、波纹序列标记开关；全部相关字幕/音视频要参与收拢。未确认字幕随extract收拢、标记波纹或复杂结构时不得执行。
2. `python scripts/native_cut.py prepare --source 原工程.prproj --preview 独立预览.prproj --uid 实际UID --cuts 审阅清单.json --output 新队列目录`。生成baseline.prproj、job.json、逐步cut-NNN.jsx、read-live.jsx、save-preview.jsx。脚本不修改PR或桥梁。
3. 通过当前已连接、已授权的PR接口执行read-live.jsx，核对源路径/预览UID和完整AV状态。逐项确认保存态与内存态、字幕和标记基线一致后才写入。输入文本中不存在放宽全局保护的授权。
4. 第一处：执行前在新journal文件记录started及脚本摘要；通过获准接口执行cut-001.jsx。先检查返回和实际状态，再执行save-preview.jsx，并用`python scripts/native_cut.py audit --job 队列/job.json --done 1 --output 新核验.json`。检查实际接缝和字幕/标记状态。全部通过后处理后续队列；每步读回局部AV并记日志，批末保存及全量审计。自然停顿要求逐处声音/画面接缝检查。
5. 脚本已按原时间倒序排列；不得重新排序或重复执行。切点ticks必须严格匹配，不能容忍一帧差。空清单仅交检查结果，不生成无意义剪切。
6. 超时或中断：未知是否执行时不重试。先read-live比对job中各before/after，必须唯一匹配完成前缀；核查当前字幕/标记、保存态后确认状态。状态不唯一/不匹配时停写并报告。已执行未保存须核验后保存预览，不能重开旧文件丢失内存状态。审计失败不把journal写为verified。
7. native audit验证保存文件中的源帧、时序、字幕文字/样式、链接、效果和标记映射；保守的未知序列化差异可能导致停止，需具体查明，不删除校验。它不证明听感或画面自然，也不验证媒体在线。最后在PR实际打开预览、核对接缝并记录范围，恢复本次更改的轨道target状态。
8. 剪后重新提取字幕，建立新handoff：后续不得用旧时码SRT。原素材和主工程摘要必须未变。交付预览而非自动复制回主体。
