# 离线准备与分类数据

以下命令中的路径由助手替换为当前文件的实际路径，用户不必编辑代码。每个序列使用新的任务目录。所有工具不会覆盖原工程。

```text
python scripts/preflight.py
python scripts/task_setup.py inspect <主工程.prproj>
python scripts/task_setup.py prepare <主工程.prproj> --uid <实际UID> --fps 50 --output <新任务目录> --latest-saved-verified
```

`--latest-saved-verified`记录助手已经核实最新保存状态，不是要求用户额外确认一次。工具不能读取未保存内存；必须先实际核对。prepare输出独立预览、来源快照、来源摘要、config.json和未审核review.json。不支持结构在复制前拒绝；复制期间来源变动则停止，留下的副本标为不可用。

## 两遍画面分析和缓存

```text
python scripts/media_samples.py <任务/config.json> --output <新首轮目录> --cache <任务/图像缓存> --pass screen
python scripts/media_samples.py <任务/config.json> --output <新候选目录> --cache <任务/图像缓存> --pass candidate --clips V1:0-100 V1:100-250
```

首轮每个已有视频片段取中间一帧，候选轮取首、中、尾；片段ID由首轮报告提供，不能复制示例数字。联系表显示片段ID和序列帧，samples.json保留源文件、源时间、序列帧和媒体身份。抽帧结束不代表已查看图片。助手实际查看联系表后将证据编号写入review；长镜头内部变化、摇摄/叠化和疑点需额外连续查看，不把3帧当作全段证明。

缓存键包含媒体完整路径、大小、修改时间、源采样时刻和规则版本。素材重剪时可复用相同源帧，但重新核对角色与序列映射；媒体被替换或缓存不可信时使用新缓存目录。源媒体帧率不必等于序列帧率，工具以源秒数定位取样。它不完成帧准确的镜头切点检测；需要新切点时在原生序列按实际帧复核。不得按低分辨率缩略图判断精细唇动。

## review.json

保留prepare产生的source_sha256、uid、fps；mode取 `audience_only` 或 `audience_and_interpreter`。

spans必须恰好覆盖每个源视频片段，不能跨已有切口。每项：

```json
{
  "video_track": 0, "start": 0, "end": 100,
  "label": "audience", "reviewed": true,
  "visual_evidence": ["candidate/samples.json中的首中尾样本；已查看，均为听讲观众"],
  "audio_role": "not_checked", "audio_evidence": [],
  "overlapping_protected_speech": false
}
```

时间为整数序列帧，轨道为从0开始的索引。label可取audience、interpreter、speaker、host、questioner、uncertain、protected。不确定镜头审核后仍用uncertain，说明疑点；reviewed只表示已检查，不表示已确定分类。不能把整段标为已查看以绕过证据。

观众类与声音类别独立，观众时有翻译声音仍label=audience、audio_role=interpreter，视频只移V2。interpreter类必须有实际音频证据、audio_role=interpreter，且无保护声音重叠；否则保留。证据写明文件、源/序列时间窗、观察内容和层级，不能写笼统“AI判断”。只有实际听到的范围可称听审，ASR或波形不等于听审。无翻译模式不要求无用的全片转写。

已确认应移轨但未实施的范围需 `retained_reason`。已在正确轨道上的片段不用再生成动作。工具校验证据字段和范围，不自动验证人类身份或声音真伪。

config中的cuts为 `{"frame":40,"video_track":0,"audio_track":0}`；moves为 `{"start":0,"end":40,"video_track":0,"audio_track":0,"target_track":1}`。每个cut必须对应一项review.cut_reviews：同样的三个位置字段，加 `"reviewed":true,"evidence":["准确切点依据和已核对的音画范围"]`。切点只为隔离需要移轨的片段，不为测试切分。每个move与一个明确分类span完全对应。其余字段与来源快照保持匹配。

## 执行前后

打开预览和激活序列是独立状态，不能把复制文件当作已打开。先核实预览实际媒体、轨道、时间、效果、字幕、标记和链接，再执行tools.md中的build、prepare_preview和run。目标轨道占用、锁定或源映射不符直接停止。

无动作时也可build生成空清单，表明哪些已正确分轨/保留。空清单不意味着所有观众已找到。需要运行结束时，对照delivery.md标明实际检查范围和零移动原因。
