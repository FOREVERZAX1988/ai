"""A2分级校正 仿真断言（2026-09-01）
标定依据：65/63/62/0004/0002 五route 882配对——视觉lead系统性偏远~1m/近距1.6m，
斜率≈1；0049/4e/4f 错配场景偏差>30%（原厂替换已有效）。
分级逻辑：ratio>0.3 原厂替换（兜底）；ratio<=0.3 70/30混合（收敛小偏差，消除临界跳变）。
用法: python3 ai/tools/test_radar_fusion_a2.py
"""
import time
import types
from types import SimpleNamespace
from openpilot.selfdrive.controls.radard import RadarD as Radard

ABST = [0.0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 6.0]
ABSI = [100, 106, 122, 168, 234, 271, 363, 380, 389, 401, 420]

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
        _macan_abstands_t=ABST,
        _macan_abstands_idx=ABSI,
        radar_state=FakeRadarState(lead1),
        v_ego=v_ego,
    )
    for m in ('_macan_fusion_enabled', '_macan_drel_to_idx', '_macan_idx_to_drel'):
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

# 场景1：小偏差(≤30%) → 70/30 混合（视觉偏远1.58m→混合后0.47m）
lead = FakeLead(drel=11.8, present=True)
fs, lead = run(lead, [can780(124)])       # 原厂 idx=124 → stock_drel≈10.217
exp = 0.7 * 10.2174 + 0.3 * 11.8          # ≈10.692
check("S1 小偏差70/30混合", abs(lead.dRel - exp) < 0.01,
      f"got {lead.dRel:.3f} exp {exp:.3f} (视觉偏远已被收敛)")

# 场景2：大偏差(>30%) → 原厂替换（错配兜底）
lead = FakeLead(drel=25.0, present=True)  # t=2.5 → vis_idx=271, ratio=118%
fs, lead = run(lead, [can780(124)])
check("S2 大偏差原厂替换", abs(lead.dRel - 10.2174) < 0.01,
      f"got {lead.dRel:.3f} exp 10.217 (错配以原厂为准)")

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
fs, sm = make_fake(lead2, [can780(124)])
Radard._macan_fuse_leads(fs, sm)
check("S5 无lead跳过", lead2.dRel == 5.0)

# 场景6：A1速度加权（0.7*原厂+0.3*视觉）
lead = FakeLead(drel=11.8, present=True, vlead=12.0)
fs, lead = run(lead, [can780(124), can804(72)])   # 原厂72km/h=20m/s
exp_v = 0.7 * 20.0 + 0.3 * 12.0
check("S6 A1速度加权", abs(lead.vLead - exp_v) < 0.01 and abs(lead.vRel - (exp_v - 10.0)) < 0.01,
      f"vLead={lead.vLead:.3f} exp {exp_v}")

print(f"\n全部通过: {n_pass}/6")
