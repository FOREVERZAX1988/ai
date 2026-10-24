"""phase 2 的 blocked_by 注释必须机器可判定，否则「还有 N 条待搬」会虚高。

一条 item 的探针成立只证明「没搬」，不证明「今天能搬」。这组用例钉住三件事：
- 合法的 blocked_by（driver-decision / submodule-pin / dependency / no-port）不报错；
- 抄错/抄旧的注释一定报错：未知 kind、dependency 不带 ref、ref 指向表外条目、
  依赖链断在半路（被依赖那条自己已无阻塞）、非 dependency 却带 ref；
- 真实登记表 ai/docs/upstream_divergence_registry.json 必须自洽（防手改漂移）。
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from ai.scripts.upstream_divergence_check import BLOCKER_KINDS, REGISTRY, check_blockers


def _item(commit: str, blocker: dict | None = None) -> dict:
  item = {"commit": commit, "subject": f"subject {commit}", "probes": []}
  if blocker is not None:
    item["blocked_by"] = blocker
  return item


class TestCheckBlockers(unittest.TestCase):
  def test_no_annotation_is_legal(self):
    self.assertEqual(check_blockers([_item("aaaaaaaaaa"), _item("bbbbbbbbbb")]), [])

  def test_every_kind_is_accepted(self):
    for kind in BLOCKER_KINDS:
      with self.subTest(kind=kind):
        items = [_item("0123456789", {"kind": kind, "reason": "why"})]
        if kind == "dependency":
          items.append(_item("aaaa000000", {"kind": "driver-decision", "reason": "blocked"}))
          items[0]["blocked_by"]["ref"] = "aaaa000000"
        self.assertEqual(check_blockers(items), [])

  def test_unknown_kind_fails(self):
    bad = check_blockers([_item("0123456789", {"kind": "someday", "reason": ""})])
    self.assertEqual(len(bad), 1)
    self.assertIn("unknown blocked_by.kind", bad[0])

  def test_dependency_without_ref_fails(self):
    bad = check_blockers([_item("0123456789", {"kind": "dependency", "reason": ""})])
    self.assertEqual(len(bad), 1)
    self.assertIn("without ref", bad[0])

  def test_dependency_ref_must_be_an_item(self):
    bad = check_blockers([_item("0123456789", {"kind": "dependency", "ref": "deadbeef01"})])
    self.assertEqual(len(bad), 1)
    self.assertIn("not an item of this table", bad[0])

  def test_open_dependency_chain_fails(self):
    # 被依赖的那条已经没有任何阻塞 => 这条其实也能搬了，登记表过期
    items = [_item("0123456789", {"kind": "dependency", "ref": "aaaa000000"}), _item("aaaa000000")]
    bad = check_blockers(items)
    self.assertEqual(len(bad), 1)
    self.assertIn("dependency chain is open", bad[0])

  def test_non_dependency_must_not_carry_ref(self):
    bad = check_blockers([_item("0123456789", {"kind": "submodule-pin", "ref": "aaaa000000"})])
    self.assertEqual(len(bad), 1)
    self.assertIn("must not carry ref", bad[0])

  def test_live_registry_is_self_consistent(self):
    registry = json.loads(Path(REGISTRY).read_text(encoding="utf-8"))
    items = registry["upstream_pending_port"]["items"]
    self.assertTrue(items, "登记表不该是空的")
    self.assertEqual(check_blockers(items), [])
    # 每条未移植条目都该说清「谁卡着它」或「今天就能搬」——现在没有无注解的漏网条目
    unannotated = [i["commit"] for i in items if not i.get("blocked_by")]
    self.assertEqual(unannotated, [], f"有未移植条目没写 blocked_by: {unannotated}")


if __name__ == "__main__":
  unittest.main()
