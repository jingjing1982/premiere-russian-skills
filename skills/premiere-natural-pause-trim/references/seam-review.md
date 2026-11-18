# 剪后可见镜头核对

只针对已核实的删除清单。先按真实画面标注可见镜头范围，不用PR片段数代替镜头。所有位置是当前序列整数帧，区间为[开始,结束)。

cuts.json在原有cuts、protected、review_reference之外增加seam_review：
```json
{
  "cuts": [[200,300]],
  "protected": [],
  "review_reference": "实际声音审阅记录与范围",
  "seam_review": {
    "preview_sha256": "本次预览文件SHA256",
    "sequence_uid": "目标序列UID",
    "fps": 25,
    "duration": 1000,
    "cuts": [[200,300]],
    "short_seconds": 0.5,
    "review_seconds": 1,
    "shots": [{"id":"shot-a", "start":0, "end":1000, "evidence":"实际已查看的画面及位置"}],
    "reviews": {}
  }
}
```
示例帧数及文字不能直接当作本次证据。shots可覆盖相关局部，但须覆盖每个剪后接缝两侧至少1秒及完整残留镜头；片头片尾按可用长度检查。阈值可显式配置，short_seconds只触发复核，不自动删镜头，review_seconds不得小于1。

先将seam_review对象独立写为JSON，运行`python scripts/seam_audit.py seam-review.json seam-result.json`。未覆盖范围或新产生的短残留会返回passed=false；调整切点及镜头范围后重新计算，或对确需保留的片段按返回key填写reviews：`{"镜头ID:原起帧:原止帧":{"action":"retain","reason":"具体必要性","evidence":"实际核对依据"}}`。不能为了通过而伪填保留理由。

native_cut.py prepare会核对预览摘要、UID、fps、总帧数和整份cuts一致，并强制该核对通过后才生成剪切队列；保存审计也会重新核对原绑定。不能绕过这个入口发出未经检查的剪切指令。最终仍需在PR连续听看每处实际接缝，检查原本很短但完整保留的镜头、A→B→A反跳和较长但无用的中间镜头。程序只计算已提交的镜头范围，不能证明镜头识别或声音判断正确。若效果/多轨结构不在原生适配器支持范围，报告而不扩大执行能力。
