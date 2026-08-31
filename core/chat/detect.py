"""Streaming content diagnostics — truncation & looping detection (shared).

Moved from ai.core.chat.jobs (2026-08-29): jobs.py ran detection post-hoc
(after the job finished), which cannot stop a live streaming loop. The same
logic now lives here so the streaming path (ai.core.chat.runner) can also
detect and abort in real time.
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
  # 2026-08-29: 中文左括号收尾（半句：引用了后续内容但被截断，如 "##数据证据（"）
  if re.search(r"[（【]$", text) and re.search(r"[\u4e00-\u9fa5]", text):
    return True
  return False


def content_looping(content: str) -> bool:
  """Degenerate loop detection (2026-08-29): model output stuck — same intent/phrase repeated.
  Threshold 8→3 for short lines (e.g. "执行：" spam, only 3 chars). Normal replies
  rarely repeat short lines 3+ times; acceptable false-positive risk.
  2026-09-01: 增强——段内重复（单行拼接循环）、去序号前缀（变体措辞循环）、
  5字子串强重复（微变体循环）。修复：变体循环（每行措辞略不同但核心短语相同）此前漏检。
  """
  if not content:
    return False
  text = re.sub(r"```.*?```", " ", content, flags=re.DOTALL)  # 排除代码块（合法重复）
  lines = [l.strip() for l in text.splitlines() if len(l.strip()) >= 3]
  if len(lines) < 6:
    # 行数不足：按短语切分检测段内重复（抓单行拼接型循环）
    segs = [s for s in re.split(r"[，。！？；：、\s]+", text) if len(s) >= 3]
    if len(segs) >= 4:
      sc = Counter(segs)
      if sc.most_common(1)[0][1] >= 3:
        return True
    return False
  # 1) 相邻行相同 ≥3（连续重复）
  adj = sum(1 for i in range(1, len(lines)) if lines[i] == lines[i - 1])
  if adj >= 3:
    return True
  # 2) 去序号后共享前8字符（同一意图变体重复——序号/引导词不同但核心短语相同）
  def _norm_line(l: str) -> str:
    l = re.sub(r"^[\d\s)）·\-、:：.]+", "", l.strip())
    return l[:8]
  prefix_counts = Counter(_norm_line(l) for l in lines)
  if prefix_counts.most_common(1)[0][1] >= 4:
    return True
  # 3) 同一行出现 ≥3 次（分散重复）
  row_counts = Counter(lines)
  if row_counts.most_common(1)[0][1] >= 3:
    return True
  # 4) 5字子串强重复（微变体循环：每行措辞略不同但含同一核心短语，如"先看按钮与截断检测"）
  subs: Counter = Counter()
  for l in lines:
    for i in range(len(l) - 4):
      subs[l[i:i + 5]] += 1
  if subs and subs.most_common(1)[0][1] >= 10:
    return True
  return False
