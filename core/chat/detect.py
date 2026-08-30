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
  """
  if not content:
    return False
  lines = [l.strip() for l in content.splitlines() if len(l.strip()) >= 3]
  if len(lines) < 6:
    return False
  # 1) 相邻行相同 ≥3（连续重复）
  adj = sum(1 for i in range(1, len(lines)) if lines[i] == lines[i - 1])
  if adj >= 3:
    return True
  # 2) ≥4 行共享前15字符（同一意图变体重复）
  prefix_counts = Counter(l[:15] for l in lines)
  if prefix_counts.most_common(1)[0][1] >= 4:
    return True
  # 3) 同一行出现 ≥3 次（分散重复）
  row_counts = Counter(lines)
  if row_counts.most_common(1)[0][1] >= 3:
    return True
  return False
