# 子模块 pin / remote-tracking ref 核查（2026-10-02）

结论先行：**本机 submodule 没有"没对齐"的问题，不需要 fetch 修复**；
真正存在的是 `opendbc` pin 与 SP 代码树的**版本错位**（Toyota 专属，与 Macan 无关）。

---

## 1. panda：远端 ref 已经是新的，无需 fetch

| 项 | 值 | 核实方式 |
|---|---|---|
| 子模块 HEAD | `4643ee2c6 适配F4` | `git -C panda log --oneline -1 HEAD` |
| 本机 `origin/sp-macan-re` | `4643ee2c6` | `git -C panda log -1 origin/sp-macan-re` |
| 远端真实值 | `4643ee2c61ef8b6ced0b9d2d194d9f018e60681f` | `git -C panda ls-remote origin sp-macan-re`（实测 8s 内返回，网络正常） |

三处一致 → 所谓"ref 还是旧的 `7d703710a`"只是**旧提交仍留在本地对象库/分支历史里**，
不是 remote-tracking ref 落后。`7d703710a` 是更早的提交，仍被
`remotes/origin/macan-long-0916/0920/0925/0926`、`master-c3` 等分支包含（`git branch -a --contains`），
属正常历史。**结论：不用跑 `git -C panda fetch`，也不需要修。**

> 判定口径：`git submodule status` 里 panda 显示为 `4643ee2c61… panda (remotes/origin/sp-macan-re)`
> —— 括号里是 HEAD 所指向的 ref，只要它与 `ls-remote` 的哈希一致即为对齐。

## 2. opendbc：pin 与 SP 代码树错位（本次仿真唯一"非 Macan"红项）

* pin：`opendbc_repo` @ `b5ee1ecb7`（分支 `align/master-c3-0929`，即 `origin/sp-macan-re` 尖端）。
* SP 树里的 `openpilot/sunnypilot/selfdrive/car/tests/test_custom_cruise.py` 导入
  `from opendbc.car.toyota.carstate import get_virtual_cruise_button, VIRTUAL_CRUISE_BUTTONS`。
* 该 API 的引入提交 `6e9536c64 feat(toyota): let supported cars own cruise set speed`
  **已被 `0e65ba76e` revert**，而这两个提交都是当前 pin 的祖先 → pin 处该 API 不存在 → `ImportError`。
* 该用例来自 openpilot fork 的 Toyota TSS2 功能并入（`2a5457e8e7`），它期待的是 SP 上游 opendbc
  的对应基线，与本仓 pin（mouxan `master-c3` 线）不同步。

**处置**：不为了一个 Toyota 用例去动 opendbc pin（会波及全部车型 + Macan 纵向三处接口）。
在上车前的仿真入口 `ai/tools/sim_test_macan.py` 里显式记为 `SKIP（已知环境/版本错位）`，
理由与复现命令见该文件 `skip_reason()`；Macan 相关回归不受影响。

**何时才需要真正修**：如果要在本仓跑 Toyota 相关功能（或 SP 上游要求该 API 的用例恢复），
再单独立项对齐 opendbc pin —— 届时按"仅动 pin、不动代码"的最小改动推进。

## 3. 复核命令（一次跑完）

```bash
cd /data/openpilot
git submodule status
git -C panda ls-remote origin sp-macan-re          # 与 submodule status 的哈希比对
git -C opendbc_repo log --oneline -1
python3 -c "from opendbc.car.toyota.carstate import get_virtual_cruise_button" || echo "opendbc pin 缺该 SP API（预期）"
```
