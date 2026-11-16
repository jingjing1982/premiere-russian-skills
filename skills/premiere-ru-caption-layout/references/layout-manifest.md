# 字体、语言边界和标题清单

由助手读取实际当前字幕、字体文件和PR渲染后生成；不是让用户填写的表，也不是自动推断的结果。文本框和字体测量未知时保留字幕，不能用默认48字号或49字符猜测。

`layout_titles.py source.srt layout.json candidate.srt report.json`

layout.json结构（以下为格式示例，不是字体/宽度默认值）：

```json
{
  "input_sha256": "实际source.srt的SHA256",
  "preferences": {"preferred_tail_words": 3, "near_balance_ratio": 0.8, "long_scripture_exception": true},
  "profiles": {
    "profile-a": {
      "font_file": "实际字体文件.ttf",
      "font_sha256": "实际字体文件SHA256",
      "font_index": 0,
      "font_size_px": 48,
      "tracking_px": 0,
      "horizontal_scale": 1,
      "mixed_styles": false
    }
  },
  "cues": {
    "1": {
      "profile": "profile-a",
      "ru_line_count": 1,
      "max_width_px": 1000,
      "calibration_reference": "实际PR渲染截图/对应字幕时码及字号字距换算证据",
      "title_reviewed": true,
      "titles": [{"start": 0, "end": 16, "text": "«Алмазная сутра»", "kind": "scripture"}]
    }
  }
}
```

start/end是将原俄语换行替换成单个普通空格之后字符串的Python字符偏移，[start,end)；必须精确匹配text，包括原有引号。示例保护«Алмазная сутра»的完整16个字符。实际执行必须按本条俄文的位置计算，不能套用示例偏移。

`ru_line_count`指定该cue前几条正文行属于俄语，剩余中文行完整保留，避免将中文栏的OK误当俄文。无标题也必须经审阅后填`titles: []`；缺少title_reviewed=true或calibration_reference的cue原样保留并列为未验证。书名种类为scripture（经）、treatise（论典）、book（普通书）；仅scripture可使用超长经名例外。

同一cue混用字体/样式时设置mixed_styles=true，通用测量器保留并报告；需分字符真实测量和PR验证才能另行处理，不能用其中一个字体替代全部。字体大小及字距要转换为经PR校准的像素，未知时不得填0。horizontal_scale=1代表无额外横向缩放，不是PR显示的百分数字面值。

输出始终标记PR_visual_status=unverified，模型计算通过不等于渲染验收。助手在PR验证后另交渲染检查表：cue、原始ticks、实际行数、标题同排或授权跨排、字体/样式、证据来源。不能直接把计算报告批量改成verified。
