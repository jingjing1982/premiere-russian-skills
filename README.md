# 俄语视频制作技能 / Russian Video Skills

8个可单独安装的本地AI助手技能，用于Premiere中的俄中字幕、手势定位、空白剪辑和HeyGen上传文件。当前安装与离线流程以Codex为验证对象；其他agent只有支持SKILL.md、本地工具及所需应用连接时才能使用，不保证所有聊天AI都能安装或控制PR。

当前发布：**1.3.0（2026-11-18）**。见[更新说明](CHANGELOG.md)和[本版离线验证](validation/release-1.3.0.json)。

## 直接对AI说

安装全部8个：

```text
请安装这个仓库skills目录里的全部8个技能到我的本地Codex技能目录：
https://github.com/jingjing1982/premiere-russian-skills
先检查已有同名技能，不覆盖我的修改；安装后检查依赖并告诉我可用状态。
这次只安装，不操作Premiere工程。
```

只装CSV转换：

```text
请安装这个技能到我的本地agent，并检查它需要的依赖：
https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/heygen-bilingual-upload
不要覆盖已有不同版本，不操作PR，不上传视频。
```

链接交给AI后，它需要具备本地文件和安装工具权限；只在网页中聊天、不能访问本地文件的AI无法替你安装。

## 技能目录

| 功能 | 单独安装链接 |
|---|---|
| [按字幕间隙合并与手势对齐](skills/ru-srt-merge-by-gaps/SKILL.md) | [`ru-srt-merge-by-gaps`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/ru-srt-merge-by-gaps) |
| [按说话轮次合并与手势对齐](skills/ru-srt-merge-by-speaker/SKILL.md) | [`ru-srt-merge-by-speaker`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/ru-srt-merge-by-speaker) |
| [生成HeyGen上传CSV](skills/heygen-bilingual-upload/SKILL.md) | [`heygen-bilingual-upload`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/heygen-bilingual-upload) |
| [调整俄语字幕换行](skills/premiere-ru-caption-layout/SKILL.md) | [`premiere-ru-caption-layout`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/premiere-ru-caption-layout) |
| [上传前压缩长空白](skills/premiere-cap-subtitle-gaps/SKILL.md) | [`premiere-cap-subtitle-gaps`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/premiere-cap-subtitle-gaps) |
| [成片自然停顿整理](skills/premiere-natural-pause-trim/SKILL.md) | [`premiere-natural-pause-trim`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/premiere-natural-pause-trim) |
| [讲座观众与翻译分轨](skills/premiere-lecture-track-sort/SKILL.md) | [`premiere-lecture-track-sort`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/premiere-lecture-track-sort) |
| [中文佛法字幕翻译为俄中双语](skills/buddhist-ru-subtitles/SKILL.md) | [`buddhist-ru-subtitles`](https://github.com/jingjing1982/premiere-russian-skills/tree/main/skills/buddhist-ru-subtitles) |

每个文件夹均包含自己的脚本和参考文件，不依赖另外一个技能的安装位置。使用时在AI中调用对应的`$技能名称`，再说明文件或序列。

## 给安装助手

如果当前Codex已有skill-installer，使用其GitHub安装入口：仓库`jingjing1982/premiere-russian-skills`，路径为上表的`skills/技能名称`；支持一次提供多个path。安装后只检查依赖，不自动接续制作任务。

也可以先下载仓库，再运行：

```text
python install.py
```

只安装指定项：

```text
python install.py --skills heygen-bilingual-upload premiere-ru-caption-layout
```

安装器默认写入当前用户的Codex技能目录；`--destination`可指定经用户确认的其他agent技能目录。安装器验证包内脚本摘要，同名不同版本会停止而非覆盖；它不会设置其他agent的发现机制，也不会安装PR桥梁。

Python 3.11+；CSV需要openpyxl，换行测量需要Pillow，各技能requirements.txt列出依赖。请在当前agent可用的隔离环境安装。需要媒体分析时还需ffmpeg/ffprobe或已有等价能力。

## Premiere前置条件

字幕翻译和CSV转换不依赖PR连接。PR任务需本机已有可用的Premiere控制连接；本仓库没有私人桥梁、令牌、签名文件或用户工程。运行preflight不等于PR写入能力通过，须按对应技能核实当前工程、版本及接口。

空白剪辑适配器目前限制为已核实的简单连续1倍速V1/A1及一对一链接。未知结构停止并报告；本发布没有跨电脑的PR实际剪辑/渲染验收。字体宽度计算不等于真实PR画面通过。

分轨技能另支持标准文件、25/50fps、1倍速、一视频一音频链接及无叠层结构；含画面或声音重叠、转场、嵌套等不直接执行。分轨不依赖俄语，识别仍须具备实际画面与对应语言的声音判断能力。

## 制作顺序

中文字幕 → 佛法俄中字幕翻译 → 已有俄中字幕和已审核红点 → 选一种合并模式 → 人工审核并调整视频 → 如需，压缩长空白 → 取得剪后最新SRT及对应视频 → 上传视频到HeyGen、下载Excel → 生成CSV。

生成后的音视频可再做自然停顿整理。俄语屏幕换行使用逐句字幕，不能把90秒配音长段当屏幕字幕。

**剪辑改变时间线后，旧SRT不能继续用于上传。** 各阶段handoff记录检查文件版本；speaker不允许漏填，混入两人的条目须先核实。

## 使用与验证

- [中文使用说明](先读这里.md)
- [验证与兼容性](验证与兼容性.md)
- [离线测试摘要](validation/summary.json)
- [原六项安装验证记录](validation/package-check.json)
- [新增分轨与七项安装验证](validation/track-sort-release.json)

合并计时技能默认俄语5.2音节/秒，不额外加停顿，每条最多90秒。它是规划估算，不保证生成后逐词口型同步。所有任务按实际已核验范围报告；不自动上传、付费生成或修改主体工程。

佛法字幕翻译自带800项术语库及编辑规则，Python仅使用标准库。规则不等于所有出版物的统一标准；支持用户明确指定其他术语库。翻译不计算配音语速、不改原时间，格式检查不能替代全文语言审校。

## 已安装用户更新

```text
请检查 https://github.com/jingjing1982/premiere-russian-skills 的最新版本，
先比较我已安装的同名技能和自定义配置，备份需要替换的旧版，
保留我的自定义改动后更新我选用的技能；发现实质冲突先说明。
完成后验证安装和依赖，只更新技能，不操作PR工程。
```

安装器不会直接覆盖不同版本；助手须先比较、保留必要恢复来源并处理自定义文件，或将新版安装到单独检查目录。不要把“已推送GitHub”理解为其他用户的本地安装自动更新。
