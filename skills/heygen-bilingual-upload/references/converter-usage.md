# 用户版入口优先

常规最终交付用scripts/upload_checked.py，它先核对handoff。下列srt_to_heygen_csv.py是其底层引擎，也用于speaker筛查和分部覆盖检查。不得因为底层命令可以单独运行就跳过版本/视频来源核对。

# 统一转换与独立验收

## 先筛查跨speaker正文

```text
python scripts/srt_to_heygen_csv.py final.srt --template-xlsx export.xlsx --audit-speakers
```

只输出JSON，不生成CSV。`blocking_cues`非空时不得交付上传版；先核对这些条目的实际讲话归属，不用中点算法代替核查。可附已确认的分部参数。

复核文件`review.json`结构：`context`完整复制本次筛查报告的context（SRT摘要、Excel摘要、原始范围及offset_ms），`reviews`是逐条复核数组：

```json
{
  "context": {"source_sha256": "本次SRT摘要", "template_sha256": "本次Excel摘要", "source_start_ms": 0, "source_end_ms": null, "offset_ms": 0},
  "reviews": [{"cue": "2", "classification": "timing_only", "speaker": "speaker_1", "evidence": {"kind": "audio_review", "reference": "实际来源文件及核查时段", "observation": "实际核查结果，说明为何正文只有一个人而时段跨标签"}}]
}
```

只接受实际听审、画面与台词联合核查或用户明确确认，kind分别为`audio_review`、`visual_dialogue_review`、`user_confirmation`。`timing_only`或`excel_label_error`需有证据并指定Excel中存在的标签；`mixed_speakers`、`unresolved`明确阻断。没有候选的条目若另有两人混入证据，也可记录mixed_speakers并阻断，不能以Excel未报警为理由忽略。

转换与`--verify-only`都必须传同一`--speaker-review review.json`；分部清单可在各part写入`speaker_review`路径。程序先重新核实版本/偏移及speaker内容检查，再验证文字和时间。复核记录不是自动声纹识别，不能伪造确认或照抄示例当成已听审。

普通转换：

```text
python scripts/srt_to_heygen_csv.py final.srt upload.csv --template-xlsx export.xlsx
python scripts/srt_to_heygen_csv.py final.srt upload.csv --template-xlsx export.xlsx --verify-only
```

已确认的视频分份（不推测帧率、首末帧含义或分界）：清单路径相对于清单文件，或使用绝对路径；时间值均为整数毫秒。下面的10000仅为示例，不是任何项目的默认分界。

```json
{
  "source": "final.srt",
  "parts": [
    {"source_start_ms": 0, "source_end_ms": 10000, "offset_ms": 0,
     "template_xlsx": "part1.xlsx", "destination": "part1.csv"},
    {"source_start_ms": 10000, "source_end_ms": null, "offset_ms": 10000,
     "template_xlsx": "part2.xlsx", "destination": "part2.csv"}
  ]
}
```

```text
python scripts/srt_to_heygen_csv.py --parts-manifest parts.json
python scripts/srt_to_heygen_csv.py final.srt part1.csv --template-xlsx part1.xlsx --source-end-ms 10000 --verify-only
python scripts/srt_to_heygen_csv.py final.srt part2.csv --template-xlsx part2.xlsx --source-start-ms 10000 --offset-ms 10000 --verify-only
```

分部覆盖、正文和源时间以原SRT为准；Excel时段按该部视频的局部时间使用。每一部先通过验收，再发布输出。程序不覆盖已有文件；发现源cue跨界、分部漏项或重复时拒绝生成，不修改源文件。

`--verify-only`不修改任何文件，检查已落盘CSV，不相信生成器自己写的“通过”记录。空speaker、Excel没有的编号、Excel有但时段不符的编号、正文/时间/notes改变和行数改变均失败。

验收报告记录逐条speaker、情况4/5列表、来源摘要和偏移。格式校验通过不等于HeyGen接受上传，也不保证Excel的说话人识别正确。
