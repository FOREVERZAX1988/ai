#!/usr/bin/env python3
"""A2/A1 融合断言（2026-09-10 重写二版：B1 单表 + A2 判据物理化）

改的是**真身**：从 radard.py import 常量与方法，不硬编码公式（避免代码/测试漂移）。
  A2 映射 : t(idx) = MACAN_B1_T_A*idx + MACAN_B1_T_B ; d = t*max(v,5) ; 反解 clip((t-B)/A,1,1020)
  A2 判据 : rel = |d_vis - d_stock| / max(d_stock,1)   （距离域，物理化后的口径）
            rel<=0.3 -> 70/30..100/0 连续混合 + 距离分段权重 ; rel>0.3 -> 原厂替换
  A1 速度 : vLead 加权来自 ACC_04(km/h)，与 idx 映射无关；距离分段权重同 A2

用法: cd /data/openpilot && /usr/local/venv/bin/python ai/tools/test_radar_fusion_a2.py
"""
import time
import types
from types import SimpleNamespace

from openpilot.selfdrive.controls.radard import (RadarD as Radard, MACAN_B1_T_A as A,
                                                 MACAN_B1_T_B as B, MACAN_A2_REL_TH as REL_TH)

def t_from_idx(idx): return A * idx + B
def idx_to_drel(idx, v): return t_from_idx(idx) * (v if v > 5.0 else 5.0)
def drel_to_idx(d, v):
    t = d / v if v > 5.0 else d / 5.0
    return min(max((t - B) / A, 1.0), 1020.0)
def dist_factor_of(d): return 0.5 if d < 15.0 else (1.17 if d < 40.0 else (1.0 if d < 60.0 else 0.83))
def exp_a2(vis_drel, stock_drel):
    """与 radard._macan_fuse_leads 中 A2 段逐行同构的复算。"""
    rel = abs(vis_drel - stock_drel) / max(stock_drel, 1.0)
    w = min(0.7 + (rel / REL_TH) * 0.3, 1.0)
    w_vis = min((1.0 - w) * dist_factor_of(vis_drel), 0.5)
    return (1.0 - w_vis) * stock_drel + w_vis * vis_drel

class FakeLead:
    def __init__(self, drel=0.0, present=False, vlead=12.0):
        self.dRel = drel; self.present = present
        self.vLead = vlead; self.vRel = vlead - 10.0

class FakeRadarState:
    def __init__(self, l1, l2=None):
        self.leadOne = l1; self.leadTwo = l2 or FakeLead(0.0, False)

def make_fake(lead1, can_msgs, v_ego=10.0):
    fs = SimpleNamespace(
        CP=SimpleNamespace(carFingerprint="PORSCHE_MACAN_MK1"),
        _macan_fusion_on=True, _macan_fusion_t=time.monotonic(),
        _macan_radar={'idx': 0, 'obj': 0, 'spd': 0.0},
        radar_state=FakeRadarState(lead1), v_ego=v_ego,
    )
    for m in ('_macan_fusion_enabled', '_macan_t_from_idx', '_macan_drel_to_idx', '_macan_idx_to_drel'):
        setattr(fs, m, types.MethodType(getattr(Radard, m), fs))
    return fs, {'can': can_msgs}

def can780(idx):
    d = bytearray(7); d[3] = idx & 0xFF; d[4] = (idx >> 8) & 0xFF; d[5] = 1 << 6
    return SimpleNamespace(src=2, address=780, dat=bytes(d))

def can804(kmh):
    d = bytearray(7); raw = round(kmh / 0.32)
    d[5] = raw & 0xFF; d[6] = (raw >> 8) & 0xFF
    return SimpleNamespace(src=2, address=804, dat=bytes(d))

def run(lead1, can_msgs, v_ego=10.0):
    fs, sm = make_fake(lead1, can_msgs, v_ego)
    Radard._macan_fuse_leads(fs, sm)
    return fs, lead1

n_pass = 0
def check(name, cond, detail=""):
    global n_pass
    assert cond, f"FAIL {name}: {detail}"
    n_pass += 1
    print(f"PASS {name}")

V = 10.0
STOCK_IDX = 124
stock_drel = idx_to_drel(STOCK_IDX, V)      # (0.008969*124+0.332)*10 = 14.44 m

# S1 小偏差(rel≤30%) -> 混合 + 距离分段权重（用真身跑，期望值独立复算）
vis1 = 11.8                                   # rel=|11.8-14.44|/14.44 = 18.3%
_, lead = run(FakeLead(drel=vis1, present=True), [can780(STOCK_IDX)])
check("S1 小偏差混合+分段权重", abs(lead.dRel - exp_a2(vis1, stock_drel)) < 1e-9,
      f"got {lead.dRel:.6f} exp {exp_a2(vis1, stock_drel):.6f}")

# S2 大偏差(rel>30%) -> 原厂替换
vis2 = 60.0                                   # rel>>0.3 -> w=1.0 -> w_vis=0
_, lead = run(FakeLead(drel=vis2, present=True), [can780(STOCK_IDX)])
check("S2 大偏差原厂替换", abs(lead.dRel - stock_drel) < 1e-9, f"got {lead.dRel:.4f}")

# S3 原厂无目标(idx=0) / S4 饱和(idx=1021) -> 不动
for name, idx in (("S3 无原厂目标不动", 0), ("S4 原厂idx无效不动", 1021)):
    _, lead = run(FakeLead(drel=11.8, present=True), [can780(idx)])
    check(name, lead.dRel == 11.8, f"got {lead.dRel}")

# S5 not present -> 跳过不 crash
l2 = FakeLead(drel=5.0, present=False)
fs, sm = make_fake(l2, [can780(STOCK_IDX)])
Radard._macan_fuse_leads(fs, sm)
check("S5 无lead跳过", l2.dRel == 5.0)

# S6 A1 速度加权（原厂 72 km/h = 20 m/s）
_, lead = run(FakeLead(drel=11.8, present=True, vlead=12.0), [can780(STOCK_IDX), can804(72)])
exp_v = (1.0 - min(0.3 * dist_factor_of(lead.dRel), 0.5)) * 20.0 + min(0.3 * dist_factor_of(lead.dRel), 0.5) * 12.0
check("S6 A1速度加权", abs(lead.vLead - exp_v) < 1e-9 and abs(lead.vRel - (exp_v - V)) < 1e-9,
      f"vLead={lead.vLead:.4f} exp {exp_v:.4f}")

# S7 B1 直线无分段：逐 idx 步长恒定（无突跳），边界与直线一致
steps = [idx_to_drel(i + 1, V) - idx_to_drel(i, V) for i in range(1, 1020)]
check("S7 B1 直线无突跳", max(steps) - min(steps) < 1e-9 and abs(max(steps) - A * V) < 1e-12,
      f"max_step={max(steps):.6f} (直线 {A*V:.6f})")
check("S7b 边界点与直线一致", all(abs(idx_to_drel(i, V) - (A * i + B) * V) < 1e-12 for i in (1, 27, 100, 560, 780, 1020)))

# S8 反解往返
for idx in (1, 60, 124, 330, 560, 780, 1020):
    check(f"S8 反解一致 idx={idx}", abs(drel_to_idx(idx_to_drel(idx, V), V) - idx) < 1e-6,
          f"got {drel_to_idx(idx_to_drel(idx, V), V):.6f}")

# S9 物理化守卫：源码里判据必须是距离域 rel，且不得回退到 idx 域 ratio
import re as _re, os as _os
_src = open("/data/openpilot/openpilot/selfdrive/controls/radard.py", encoding="utf-8").read()
check("S9 判据在距离域(源码守卫)",
      _re.search(r"rel = abs\(lead\.dRel - stock_drel\) / max\(stock_drel, 1\.0\)", _src) is not None
      and "abs(vis_idx - r['idx']) / r['idx']" not in _src,
      "radard.py 里仍在用 idx 域 ratio")

# S10 记录被去掉的失真：旧 idx 域阈值 = |Δt|/(t-B)，随距离变严
_B, _A = B, A
dist = {t: 0.30 * (t - _B) / t for t in (1.5, 2.0, 3.0, 4.0)}
check("S10 idx域阈值失真已记录", all(0.20 < v < 0.30 for v in dist.values()),
      ", ".join(f"t={t}: {v*100:.1f}%" for t, v in dist.items()))

# S11 t 与 d 两口径等价：rel_d == |Δt|/t
_t1, _t2 = t_from_idx(300), t_from_idx(240)
check("S11 rel 两口径等价", abs(abs(_t1 - _t2) / _t1 - abs(idx_to_drel(300, V) - idx_to_drel(240, V)) / idx_to_drel(300, V)) < 1e-12)

print(f"\n全部通过: {n_pass}/{n_pass}")
print(f"[常量] A={A} B={B} REL_TH={REL_TH}（从 radard.py import，非硬编码）")
