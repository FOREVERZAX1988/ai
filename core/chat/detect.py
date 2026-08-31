"""Streaming content diagnostics — truncation & looping detection (shared).

Moved from ai.core.chat.jobs (2026-08-29): jobs.py ran detection post-hoc
(after the job finished), which cannot stop a live streaming loop. The same
logic now lives here so the streaming path (ai.core.chat.runner) can also
detect and abort in real time.

2026-09-01 fix: 修复误伤——5字子串只统计纯中文、表格行(含|)不参与前缀/子串
检测、段内短语阈值 3→4 且长度≥4。原因：时间线/信号表格行结构相似（如
"st3/0/45/0.10/0"）导致子串计数虚高→正常表格输出被误判循环→runner abort
→生成中断（复现：20行时间线表格误判True）。真循环（中文变体措辞重复）
检测不受影响。
"""

import re
from collections import Counter


def content_truncated(content: str) -> bool:
  """Heuristic truncation detection (aligned with frontend isContentTruncated)."""
  if not content:
    return False
  text = content.strip()
  if text.count("```") % 2 == 1:
    return True
  if re.search(r"[，、；：——]$", text):
    return True
  if re.search(r"[,;:]$", text) and re.search(r"[\u4e00-\u9fa5]", text):
    return True
  if re.search(r"[但而因所以然仍则却且与及或]$", text):
    return True
  if re.search(r"[（【]$", text) and re.search(r"[\u4e00-\u9fa5]", text):
    return True
  return False


def _pure_cn5(s: str) -> bool:
  """5字符纯中文子串（表格/信号串/时间戳含符号数字，不算）"""
  return re.fullmatch(r"[\u4e00-\u9fa5]{5}", s) is not None


def content_looping(content: str) -> bool:
  """Degenerate loop detection. 2026-09-01 修复误伤：
  - 表格行（含"|"）是合法结构输出，不参与"前缀/子串"类检测（仍参与完全相同重复检测）
  - 5字子串只统计纯中文（时间线/信号串如 "st3/0/45/0.10/0" 不再虚高）
  - 段内短语检测：长度≥4 且重复≥4 次（防"确认1…确认2…"等常见词误伤短回复）
  """
  if not content:
    return False
  text = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)  # 排除代码块（合法重复）
  lines = [l.strip() for l in text.splitlines() if len(l.strip()) >= 3]
  def _norm_line(l: str) -> str:
    l = re.sub(r"^[\d\s)）·\-、:：.]+", "", l.strip())
    return l[:8]
  if len(lines) < 6:
    # 行数不足：先去序号前缀检测（短循环：行核心相同，如"执行：先检查按钮与截断检测"+变体）
    if len(lines) >= 4:
      prefix_counts = Counter(_norm_line(l) for l in lines)
      if prefix_counts.most_common(1)[0][1] >= 4:
        return True
    # 再按短语切分检测段内重复（抓单行拼接型循环）
    segs = [s for s in re.split(r"[，。！？；：、\s]+", text) if len(s) >= 4]
    if len(segs) >= 6:
      sc = Counter(segs)
      if sc.most_common(1)[0][1] >= 4:
        return True
    return False
  # 1) 相邻行相同 ≥3（连续重复）
  adj = sum(1 for i in range(1, len(lines)) if lines[i] == lines[i - 1])
  if adj >= 3:
    return True
  # 2) 去序号后共享前8字符（同一意图变体重复）——仅非表格行
  non_table = [l for l in lines if "|" not in l]
  if len(non_table) >= 4:
    prefix_counts = Counter(_norm_line(l) for l in non_table)
    if prefix_counts.most_common(1)[0][1] >= 4:
      return True
  # 3) 同一行出现 ≥3 次（分散重复，表格行也查）
  row_counts = Counter(lines)
  if row_counts.most_common(1)[0][1] >= 3:
    return True
  # 4) 纯中文5字子串强重复（微变体循环：中文核心短语反复出现）
  subs: Counter = Counter()
  for l in non_table:
    for i in range(len(l) - 4):
      s = l[i:i + 5]
      if _pure_cn5(s):
        subs[s] += 1
  if subs and subs.most_common(1)[0][1] >= 10:
    return True
  return False
