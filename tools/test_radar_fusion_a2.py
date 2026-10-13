#!/usr/bin/env python3
"""Macan 原厂雷达融合（视觉主导，2026-10-09 语义反转）——行为断言
================================================================================
背景（本文件曾叫 test_radar_fusion_a2.py，测的是**已删除**的 A2「原厂主导 + 连续权重」
方案：MACAN_A2_REL_TH 已从 radard.py 移除，见 `_macan_fuse_leads` 的 docstring）。
旧 A2 走 idx 域连续混合、原厂权重 0.7~1.0；route 00000091 seg9 实锤其病灶：静止时原厂
idx 冻结、d_stock 退化成常数，把当天唯一准确的视觉距离整段丢掉（dRel 钉在 10.09 m 达 11 s）。

现语义（视觉主导、雷达只能改近，单向）——本文件按此重写：
  1. 视觉可用（leadsV3[i].prob >= MACAN_VISION_PROB_MIN=0.5）→ 距离/vLead 以【视觉】为基准；
  2. 原厂 idx 换算距离仅当【更近】且过 sanity 门（max(REL_GATE*d_vis, MIN_GAP)）才采纳；
  3. vLead 同理：原厂前车速度只允许把 vLead 改【低】，权重 <= V_MAX_W；
  4. 视觉无目标而原厂有目标 → 保留上游 get_lead 结果；
  5. 一阶低通(rc=SMOOTH_RC) + 单帧变化率限幅(RATE_MIN_STEP + RATE_VFACTOR*v*DT_MDL)；
     目标骤近超门(>max(RESEED_MIN_JUMP, RESEED_STEP_FACTOR*max_step)) → 判换人、重播种。

改的是**真身**：从 radard.py import 常量与方法，不硬编码公式（避免代码/测试漂移）。
用法: cd /data/openpilot && python3 ai/tools/test_radar_fusion_a2.py
"""
import sys
import time
import types
from types import SimpleNamespace

sys.path.insert(0, '/data/openpilot')

from openpilot.common.realtime import DT_MDL
from openpilot.selfdrive.controls.radard import (
    RadarD as Radard,
    MACAN_B1_T_A as A, MACAN_B1_T_B as B,
    MACAN_FUSE_REL_GATE as REL_GATE, MACAN_FUSE_MIN_GAP as MIN_GAP,
    MACAN_FUSE_V_MAX_W as V_MAX_W, MACAN_VISION_PROB_MIN as VISION_PROB_MIN,
    MACAN_SMOOTH_RC as SMOOTH_RC, MACAN_RATE_MIN_STEP as RATE_MIN_STEP,
    MACAN_RATE_VFACTOR as RATE_VFACTOR, MACAN_RESEED_MIN_JUMP as RESEED_MIN_JUMP,
    MACAN_RESEED_STEP_FACTOR as RESEED_STEP_FACTOR, RADAR_TO_CAMERA,
)
import openpilot.selfdrive.controls.radard as _radard

V = 10.0
MAX_STEP = RATE_MIN_STEP + RATE_VFACTOR * V * DT_MDL     # 单帧允许变化(m)
RESEED_TH = max(RESEED_MIN_JUMP, RESEED_STEP_FACTOR * MAX_STEP)

n_pass = 0
def check(name, cond, detail=""):
    global n_pass
    assert cond, f"FAIL {name}: {detail}"
    n_pass += 1
    print(f"PASS {name}")


def t_from_idx(idx):
    return A * idx + B

def idx_to_drel(idx, v):
    return t_from_idx(idx) * (v if v > 5.0 else 5.0)


class FakeLead:
    def __init__(self, drel=0.0, present=False, vlead=12.0):
        self.dRel = drel; self.present = present
        self.vLead = vlead; self.vLeadK = vlead; self.vRel = vlead - V

class FakeRadarState:
    def __init__(self, l1, l2=None):
        self.leadOne = l1; self.leadTwo = l2 or FakeLead(0.0, False)

class FakeLeadV3:
    """modelV2.leadsV3[i]：x/v 是数组(取[0])，prob 为可信度。"""
    def __init__(self, x, v, prob):
        self.x = [x]; self.v = [v]; self.prob = prob


def can780(idx):
    d = bytearray(7); d[3] = idx & 0xFF; d[4] = (idx >> 8) & 0xFF; d[5] = 1 << 6
    return SimpleNamespace(src=2, address=780, dat=bytes(d))

def can804(kmh):
    d = bytearray(7); raw = round(kmh / 0.32)
    d[5] = raw & 0xFF; d[6] = (raw >> 8) & 0xFF
    return SimpleNamespace(src=2, address=804, dat=bytes(d))


def make_fake(lead1, can_msgs, lead2=None, v_ego=V):
    """最小 Radard 壳：只带 _macan_fuse_leads 需要的状态，不跑 __init__（避免重型依赖）。"""
    fs = SimpleNamespace(
        CP=SimpleNamespace(carFingerprint="PORSCHE_MACAN_MK1", openpilotLongitudinalControl=True),
        _macan_fusion_on=True, _macan_fusion_t=time.monotonic(),   # 1s 缓存窗口内 → enabled 直接返回 True
        _macan_radar={'idx': 0, 'obj': 0, 'spd': 0.0},
        radar_state=FakeRadarState(lead1, lead2), v_ego=v_ego,
        _macan_smooth={}, _macan_smooth_v={}, _macan_last_fused={},
        _macan_last_valid_idx=0.0, _macan_hyst_t0=0.0, _macan_hyst_invalid=False, _macan_hyst_win=0.6,
    )
    for m in ('_macan_fusion_enabled', '_macan_t_from_idx', '_macan_drel_to_idx',
              '_macan_idx_to_drel', '_macan_reset_lead'):
        setattr(fs, m, types.MethodType(getattr(Radard, m), fs))
    return fs, {'can': list(can_msgs)}


def step(fs, sm, leads_v3):
    Radard._macan_fuse_leads(fs, sm, leads_v3)
    return fs.radar_state.leadOne


def run(lead1, can_msgs, leads_v3, lead2=None):
    fs, sm = make_fake(lead1, can_msgs, lead2)
    return step(fs, sm, leads_v3)


STOCK_IDX = 124
STOCK_DREL = idx_to_drel(STOCK_IDX, V)      # (0.008969*124+0.332)*10 = 14.4416 m

# ---- 1) 视觉主导：雷达更远绝不采纳 ----
# d_vis = 13.52 - 1.52 = 12.0；原厂 14.44 更远 → 保留视觉
l = run(FakeLead(drel=999.0, present=True), [can780(STOCK_IDX)], [FakeLeadV3(13.52, 1.42, 0.9)])
check("视觉主导：雷达更远不采纳 → dRel=12.0", abs(l.dRel - 12.0) < 1e-9, f"got {l.dRel}")

# ---- 2) 雷达更近且过 sanity 门 → 采纳（安全方向）----
# d_vis=20-1.52=18.48；原厂 14.44 更近，差 4.04 <= gate max(0.25*18.48, 2)=4.62
l = run(FakeLead(present=True), [can780(STOCK_IDX)], [FakeLeadV3(20.0, 1.0, 0.9)])
check("雷达更近且过门 → 采纳原厂 14.44", abs(l.dRel - STOCK_DREL) < 1e-9, f"got {l.dRel}")

# ---- 3) 雷达更近但超门 → 拒绝（用视觉，避免原厂异常把距离拉爆）----
# d_vis=21.52-1.52=20.0；原厂 idx=19 → 5.02，差 14.98 > gate 5 → 拒绝
l = run(FakeLead(present=True), [can780(19)], [FakeLeadV3(21.52, 1.0, 0.9)])
check("雷达更近但超 sanity 门 → 拒绝（用视觉 20.0）", abs(l.dRel - 20.0) < 1e-9, f"got {l.dRel}")

# ---- 4) 视觉不可用 → 保留上游 get_lead 结果，不改 dRel ----
l = run(FakeLead(drel=9.0, present=True), [can780(STOCK_IDX)], [FakeLeadV3(13.52, 0.0, 0.1)])
check("视觉未确认(prob<0.5) → 保留上游 dRel=9.0", l.dRel == 9.0, f"got {l.dRel}")
l = run(FakeLead(drel=9.0, present=True), [can780(STOCK_IDX)], [])
check("leadsV3 为空 → 保留上游 dRel=9.0", l.dRel == 9.0, f"got {l.dRel}")

# ---- 5) 无前车(present=False) → 跳过且复位，不 crash ----
l = run(FakeLead(drel=5.0, present=False), [can780(STOCK_IDX)], [FakeLeadV3(13.52, 0.0, 0.9)])
check("无前车 → 不 crash、dRel 不变", l.dRel == 5.0, f"got {l.dRel}")

# ---- 6) vLead 单向：只降不升，权重 <= V_MAX_W ----
l = run(FakeLead(present=True, vlead=12.0), [can780(STOCK_IDX), can804(72)],
        [FakeLeadV3(13.52, 12.0, 0.9)])           # 原厂 72km/h=20 > 视觉 12 → 不采纳
check("vLead 只降不升：原厂更快(20>12)不采纳 → 12.0", abs(l.vLead - 12.0) < 1e-9, f"got {l.vLead}")
l = run(FakeLead(present=True, vlead=12.0), [can780(STOCK_IDX), can804(32)],
        [FakeLeadV3(13.52, 12.0, 0.9)])           # 原厂 32km/h=8.889 < 视觉 12 → 0.3 权重并低
exp_v = (1.0 - V_MAX_W) * 12.0 + V_MAX_W * (32.0 / 3.6)
check("vLead 只降：原厂更慢(8.89<12)按 0.3 权重并低", abs(l.vLead - exp_v) < 1e-9, f"got {l.vLead} exp {exp_v}")
check("vRel = vLead - v_ego", abs(l.vRel - (exp_v - V)) < 1e-9, f"got {l.vRel}")

# ---- 7) 变化率限幅：单帧 dRel 增量受 max_step 约束（压制源切换瞬跳）----
lead = FakeLead(present=True)
fs, sm = make_fake(lead, [can780(STOCK_IDX)])
step(fs, sm, [FakeLeadV3(13.52, 0.0, 0.9)])        # 视觉 12.0
prev = lead.dRel
l = step(fs, sm, [FakeLeadV3(21.52, 0.0, 0.9)])    # 视觉跳到 20.0
check(f"变化率限幅：单帧增幅 ≤ max_step({MAX_STEP:.2f})",
      prev < l.dRel <= prev + MAX_STEP + 1e-9, f"{prev} -> {l.dRel}")

# ---- 8) 换人检测：骤近超门 → 重播种到新目标真实距离 ----
lead = FakeLead(present=True)
fs, sm = make_fake(lead, [can780(STOCK_IDX)])
for _ in range(30):
    step(fs, sm, [FakeLeadV3(21.52, 0.0, 0.9)])    # 稳定在 ~20
l = step(fs, sm, [FakeLeadV3(11.52, 0.0, 0.9)])    # 骤近到 10.0（差 10 > reseed 门）
check("换人检测：骤近超门 → 重播种 ≈10", abs(l.dRel - 10.0) < 0.2, f"got {l.dRel}")

# ---- 9) 无效保持(hysteresis)：idx 短暂失效沿用最近有效 idx ----
lead = FakeLead(present=True)
fs, sm = make_fake(lead, [can780(STOCK_IDX)])
step(fs, sm, [FakeLeadV3(21.52, 0.0, 0.9)])
check("hysteresis：记录有效 idx=124", fs._macan_last_valid_idx == STOCK_IDX, f"got {fs._macan_last_valid_idx}")
sm['can'] = [can780(0)]                            # 原厂 idx 变无效（窗口内）
step(fs, sm, [FakeLeadV3(21.52, 0.0, 0.9)])
check("hysteresis：窗口内保持 last_valid=124 且进入无效态",
      fs._macan_last_valid_idx == STOCK_IDX and fs._macan_hyst_invalid is True,
      f"idx={fs._macan_last_valid_idx} invalid={fs._macan_hyst_invalid}")

# ---- 10) B1 标定映射：直线无突跳 + 反解往返一致（走真身方法）----
fs, _ = make_fake(FakeLead(), [])
check("_macan_idx_to_drel 与 B1 直线一致",
      abs(fs._macan_idx_to_drel(560, V) - idx_to_drel(560, V)) < 1e-9)
check("_macan_drel_to_idx 往返一致",
      abs(fs._macan_drel_to_idx(idx_to_drel(560, V), V) - 560) < 1e-6)
steps = [idx_to_drel(i + 1, V) - idx_to_drel(i, V) for i in range(1, 1020)]
check("B1 直线无突跳且步长 = A*v", max(steps) - min(steps) < 1e-9 and abs(max(steps) - A * V) < 1e-12,
      f"max_step={max(steps):.6f} (直线 {A*V:.6f})")

# ---- 11) 源码守卫：确认已迁移到新语义，且旧 A2 权重公式已不在 ----
_src = open("/data/openpilot/openpilot/selfdrive/controls/radard.py", encoding="utf-8").read()
check("源码守卫：A2 连续权重公式已移除",
      "rel = abs(lead.dRel - stock_drel) / max(stock_drel, 1.0)" not in _src,
      "radard.py 里仍存在旧 A2 权重公式")
check("模块守卫：MACAN_A2_REL_TH 已删除（本测已迁移到新语义）",
      not hasattr(_radard, "MACAN_A2_REL_TH"))

print(f"\n全部通过: {n_pass}/{n_pass}")
print(f"[常量] A={A} B={B} REL_GATE={REL_GATE} MIN_GAP={MIN_GAP} V_MAX_W={V_MAX_W} "
      f"VISION_PROB_MIN={VISION_PROB_MIN} SMOOTH_RC={SMOOTH_RC} MAX_STEP={MAX_STEP:.2f} RESEED_TH={RESEED_TH:.2f}")
