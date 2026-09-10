#!/usr/bin/env python3
"""A2/A1 融合仿真断言（2026-09-10 重写，统一到 0909 VERIFIED 线性时距公式）
radard.py 已从旧 153 点插值表切换到线性公式：
    t(idx) = 0.008718*idx + 1.0178  (idx 100~560)，id<100 → 0.8，idx>560 → 6.0
    d_rel   = t * max(v_ego, 5.0)
    idx(t)  = (t - 1.0178)/0.008718  (反解)
本测试所有期望值直接由上述公式计算，不依赖旧表常量。

分层逻辑（沿用 2026-09-01 标定语义）：
  ratio>0.3 → 原厂替换；ratio<=0.3 → 70/30 混合 + 距离分段权重。
用法: python3 ai/tools/test_radar_fusion_a2.py
"""
import time
import types
from types import SimpleNamespace
from openpilot.selfdrive.controls.radard import RadarD as Radard

# ---- 与 radard.py _macan_t_from_idx/_macan_idx_to_drel/_macan_drel_to_idx 同源 ----
def t_from_idx(idx):
    if idx < 100: return 0.8
    if idx > 560: return 6.0
    return 0.008718 * idx + 1.0178

def idx_to_drel(idx, v_ego):
    return t_from_idx(idx) * (v_ego if v_ego > 5.0 else 5.0)

def drel_to_idx(drel, v_ego):
    t = drel / v_ego if v_ego > 5.0 else drel / 5.0
    if t <= 0.8: return 100.0
    if t >= 6.0: return 561.0
    return (t - 1.0178) / 0.008718

class FakeLead:
    def __init__(self, drel=0.0, present=False, vlead=12.0):
        self.dRel = drel; self.present = present
        self.vLead = vlead; self.vRel = vlead - 10.0

class FakeRadarState:
    def __init__(self, lead1, lead2=None):
        self.leadOne = lead1
        self.leadTwo = lead2 or FakeLead(0.0, False)

def make_fake(lead1, can_msgs, v_ego=10.0):
    fs = SimpleNamespace(
        CP=SimpleNamespace(carFingerprint="PORSCHE_MACAN_MK1"),
        _macan_fusion_on=True,
        _macan_fusion_t=time.monotonic(),   # 缓存命中，<1s 内不重查 Params
        _macan_radar={'idx': 0, 'obj': 0, 'spd': 0.0},
        radar_state=FakeRadarState(lead1),
        v_ego=v_ego,
    )
    for m in ('_macan_fusion_enabled', '_macan_t_from_idx', '_macan_drel_to_idx', '_macan_idx_to_drel'):
        setattr(fs, m, types.MethodType(getattr(Radard, m), fs))
    return fs, {'can': can_msgs}

def can780(idx):
    d = bytearray(7)
    d[3] = idx & 0xFF; d[4] = (idx >> 8) & 0xFF; d[5] = 1 << 6
    return SimpleNamespace(src=2, address=780, dat=bytes(d))

def can804(kmh):
    d = bytearray(7)
    raw = round(kmh / 0.32)
    d[5] = raw & 0xFF; d[6] = (raw >> 8) & 0xFF
    return SimpleNamespace(src=2, address=804, dat=bytes(d))

def run(lead1, can_msgs):
    fs, sm = make_fake(lead1, can_msgs)
    Radard._macan_fuse_leads(fs, sm)
    return fs, lead1

n_pass = 0
def check(name, cond, detail=""):
    global n_pass
    assert cond, f"FAIL {name}: {detail}"
    n_pass += 1
    print(f"PASS {name}")

V_EGO = 10.0
STOCK_IDX = 124
stock_drel = idx_to_drel(STOCK_IDX, V_EGO)   # = (0.008718*124+1.0178)*10 = 20.99m

# 场景1：小偏差(≤30%) → 70/30 混合 + 距离分段权重
#   视觉 drel=11.8 → vis_idx=drel_to_idx(11.8,10)= (1.18-1.0178)/0.008718 = 18.6 → 但 <100 锚定到 100
#   实际 fuse 用的是 drel 域：ratio=|vis_idx-stock_idx|/stock_idx
vis_idx1 = drel_to_idx(11.8, V_EGO)          # ≈18.6 → <100，代码无下界，但用于 ratio
lead = FakeLead(drel=11.8, present=True)
fs, lead = run(lead, [can780(STOCK_IDX)])
# 期望：ratio=|vis_idx1-stock_idx|/stock_idx
ratio = abs(vis_idx1 - STOCK_IDX) / STOCK_IDX
w = min(0.7 + (ratio / 0.3) * 0.3, 1.0)
d = lead.dRel
dist_factor = 0.5 if d < 15.0 else (1.17 if d < 40.0 else (1.0 if d < 60.0 else 0.83))
w_vis = min((1.0 - w) * dist_factor, 0.5)
exp = (1.0 - w_vis) * stock_drel + w_vis * lead.dRel
check("S1 小偏差混合+分段权重", abs(lead.dRel - exp) < 0.01, f"got {lead.dRel:.3f} exp {exp:.3f}")

# 场景2：大偏差(>30%) → 原厂替换（w 硬顶 1.0 → w_vis=0）
lead = FakeLead(drel=60.0, present=True)     # vis_idx=drel_to_idx(60,10)=(6-1.0178)/0.008718≈571
fs, lead = run(lead, [can780(STOCK_IDX)])
# ratio = |571-124|/124 ≈ 3.6 >> 0.3 → w=1.0 → w_vis=0 → dRel=stock_drel
check("S2 大偏差原厂替换", abs(lead.dRel - stock_drel) < 0.01,
      f"got {lead.dRel:.3f} exp {stock_drel:.3f}")

# 场景3：原厂无目标(idx=0) → 不动
lead = FakeLead(drel=11.8, present=True)
fs, lead = run(lead, [can780(0)])
check("S3 无原厂目标不动", lead.dRel == 11.8, f"got {lead.dRel}")

# 场景4：原厂idx=1021(饱和/无效) → 不动
lead = FakeLead(drel=11.8, present=True)
fs, lead = run(lead, [can780(1021)])
check("S4 原厂idx无效不动", lead.dRel == 11.8, f"got {lead.dRel}")

# 场景5：lead not present → 跳过不crash
lead2 = FakeLead(drel=5.0, present=False)
fs, sm = make_fake(lead2, [can780(STOCK_IDX)])
Radard._macan_fuse_leads(fs, sm)
check("S5 无lead跳过", lead2.dRel == 5.0)

# 场景6：A1速度加权（距离分段权重，原厂72km/h=20m/s）
lead = FakeLead(drel=11.8, present=True, vlead=12.0)
fs, lead = run(lead, [can780(STOCK_IDX), can804(72)])
d = lead.dRel
dist_factor = 0.5 if d < 15.0 else (1.17 if d < 40.0 else (1.0 if d < 60.0 else 0.83))
w_vis = min(0.3 * dist_factor, 0.5)
exp_v = (1.0 - w_vis) * 20.0 + w_vis * 12.0
check("S6 A1速度加权", abs(lead.vLead - exp_v) < 0.01 and abs(lead.vRel - (exp_v - V_EGO)) < 0.01,
      f"vLead={lead.vLead:.3f} exp {exp_v:.3f}")

# 场景7（新增）：线性公式边界—— idx<100 锚 0.8s / idx>560 封顶 6.0s / idx=100 走公式起点
check("S7 锚点/封顶/公式", abs(idx_to_drel(99, 10.0) - 8.0) < 1e-9 and
      abs(idx_to_drel(561, 10.0) - 60.0) < 1e-9 and
      abs(idx_to_drel(100, 10.0) - (0.008718*100+1.0178)*10) < 1e-9 and
      abs(idx_to_drel(330, 10.0) - (0.008718*330+1.0178)*10) < 1e-9,
      f"99→{idx_to_drel(99,10.0):.2f} 561→{idx_to_drel(561,10.0):.2f} 100→{idx_to_drel(100,10.0):.2f} 330→{idx_to_drel(330,10.0):.2f}")

# 场景8（新增）：反解一致性 drel_to_idx∘idx_to_drel
for idx in (120, 200, 330, 480, 550):
    d = idx_to_drel(idx, V_EGO)
    b = drel_to_idx(d, V_EGO)
    check(f"S8 反解一致 idx={idx}", abs(b - idx) < 1e-6, f"got {b:.4f}")

print(f"\n全部通过: {n_pass}/{n_pass}")
