"""Readable companion report for speaker-mode plans; does not edit Premiere."""
from pathlib import Path
from gesture_timing import fmt
from fractions import Fraction

def write_report(result,path):
    src=result.get('source') or {};fps=Fraction(str(src['fps'])) if src.get('fps') else None;rows=result['groups'];lookup={r['group']:r for r in rows}
    def tc(ms):
        if not fps:return '未提供帧率'
        if fps.denominator!=1:return f'约第{round(abs(ms)*fps/1000)}帧（{fps}fps，非DF显示时码）'
        f=round(abs(ms)*fps/1000);s,f=divmod(f,int(fps));m,s=divmod(s,60);h,m=divmod(m,60)
        return ('-' if ms<0 else '')+f'{h:02}:{m:02}:{s:02}:{f:02}'
    def span(ms):
        return f'{ms/1000:+.3f}秒'+(f'（{round(ms*fps/1000):+d}帧）' if fps else '')
    out=[f"# {src.get('sequence_name','序列')}：合并字幕定位核对",'',
      f"来源工程：{src.get('project','未记录')}",f"来源SHA256：{src.get('source_sha256','未记录')}",
      f"序列UID：{src.get('sequence_uid','未记录')}；帧率：{fps or '未记录'}。",'',
      f"原字幕{sum(len(r['cue_ids']) for r in rows)}条 → 合并{len(rows)}条；说话轮次{len(result['turns'])}个；红点{len(result['anchors'])}个。",
      f"{result['speed']}音节/秒，不另加停顿；每条原跨度及规划时长均不超过{result.get('max_duration_ms',90000)/1000:g}秒。每段首个红点优先，其余点只报告。",
      '这是字幕和画面证据下的规划估算，没有实际俄语生成音频的逐词时间验证，不代表口型已精确同步。',
      '字幕按原文顺序逐条合并；未改PR、原字幕或红点。存在接缝/边界疑点时，SRT是核对稿，不是无冲突成片方案。','',
      '## 需要处理的接缝','',
      '|前段→后段|前段结束→后段开始|空隙＋／重叠－|同一轮次|','|---|---|---|---|']
    problems=[j for j in result['joins'] if j['needs_review']]
    for j in problems:
        a=lookup[j['before_group']];b=lookup[j['after_group']]
        out.append(f"|{a['group']}→{b['group']}|{fmt(a['end_ms'])} → {fmt(b['start_ms'])}|{span(j['gap_ms'])}|{'是' if j['same_turn'] else '否'}|")
    if not problems:out.append('|无||||')
    out+=['','同轮次正空隙来自按本次语速计算的俄语比对应原画面短、各首锚又分别固定。不能同时保证这些锚点、固定语速和全程无缝；本稿按你选定的首锚优先保留。','',
      '## 源轮次边界及其他异常','']
    labels={'before_turn_source_start':'早于该说话轮次原字幕开始','after_turn_source_end':'晚于该说话轮次原字幕结束','negative_start':'负起点','video_overflow':'超出视频末尾','sentence_split_at_cue_boundary':'过长整句在原cue边界分组'}
    for x in result['boundary_issues']:out.append(f"- 第{x['group']}条：{labels[x['type']]}，{span(x.get('ms',0))}。")
    if not result['boundary_issues']:out.append('无。')
    for x in result['source_issues']:out.append(f'- 源字幕异常：{x}')
    for t in result['turns']:
        if '待' in t['speaker']:out.append(f"- {t['speaker']}，原cue {t['cue_ids']}；已独立保留，未猜并进其他人。")
    out+=['','## 红点逐点定位','', '|红点|PR帧时码|原cue／合并条|对应中俄词语|主锚|预计偏差|','|---|---|---|---|---|---|']
    for a in result['anchors']:
        out.append(f"|{a['id']}|{tc(a['marker_ms'])}|{a['cue_id']}／{a['group']}|{a['target_zh']} / {a['target_ru'] or '原俄语致谢句末'}|{'是' if a['primary'] else '否'}|{a['error_ms']/1000:+.3f}秒|")
    out+=['','### 定位依据与替代方案','']
    for a in result['anchors']:
        out.append(f"- {a['id']}：{a['evidence']}。对齐基准：{a['alignment_basis']}。单独对准此点：第{a['group']}条起止 {fmt(a['alternative_start_ms'])}—{fmt(a['alternative_end_ms'])}；整条移动 {span(a['shift_ms'])}。")
    out+=['','## 手动定位方法','',
      '调整前先复制序列或留备份。整条字幕移动会改变该条内所有词的预计位置；对准次锚会失去原首锚对齐，并可能影响相邻接缝。只拉长末尾不能确定某个内部词的实际发音位置。',
      '按上表给出的替代起止整体平移字幕并保持时长，再检查前后空隙/重叠。若已经生成HeyGen音频，应先找到目标俄语词实际发音时刻：移动量＝红点时刻－实际词时刻；这是实际校准，不再依赖音节估算。',
      '换人处不能把重叠的两条简单合并。没有用户决定，不自动提速、删句、移动红点或剪视频。','',
      '## 全部分组','',
      '|条目／说话人|原cue|源起止|新起止|新起止PR帧码|音节／时长|','|---|---|---|---|---|---|']
    for r in rows:
        out.append(f"|{r['group']} {r['speaker']}|{r['cue_ids'][0]}—{r['cue_ids'][-1]}|{fmt(r['source_start_ms'])}—{fmt(r['source_end_ms'])}|{fmt(r['start_ms'])}—{fmt(r['end_ms'])}|{tc(r['start_ms'])}—{tc(r['end_ms'])}|{r['syllables']} / {r['duration_ms']/1000:.3f}秒|")
    out+=['','## 全部相邻接缝（含换人留白）','', '|前条→后条|间隔|同轮次|','|---|---|---|']
    for j in result['joins']:out.append(f"|{j['before_group']}→{j['after_group']}|{span(j['gap_ms'])}|{'是' if j['same_turn'] else '否'}|")
    out+=['',f"SRT SHA256：{result.get('srt_sha256','尚未导出')}。",'文字回读核验：'+str(result.get('text_readback_verified',False))+'。','']
    Path(path).write_text('\n'.join(out),'utf-8-sig')
