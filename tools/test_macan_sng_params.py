#!/usr/bin/env python3
"""Macan SnG 视觉源通道（CC_SP.params）冒烟测试
=================================================
覆盖 2026-10-07 新增的 SnG 闸门视觉源链路：

  modelV2.leadsV3[0]  --(controlsd_ext.state_control_ext)-->  CC_SP.params
      [visLeadDist / visLeadVLead]  --(capnp / convert_carControlSP)-->  carcontroller

关键背景（务必保留这段注释）：
  * 传参机制：pycapnp 2.1.0 的 _DynamicListBuilder **没有 append()**，历史代码
    `CC_SP.params.append()` 抛 AttributeError 被 except 吞掉 → 参数从未送达
    carcontroller（route 00000049 实测 carControlSP.params 恒为 []）。本文件用
    「整表赋值」重写该通道，并断言消费侧（convert_carControlSP → `_p.get("key")`）可用。
  * 视觉源必须是 **modelV2 原始前车**，不能用 CS.op_lead_dRel（radard 融合值，原厂 idx
    冻结时会被钉成常数，00000091 seg9 钉在 10.09 m）。
  * leadsV3 是雷达坐标系（RADAR_TO_CAMERA = 1.52 m 前置），送出前减 1.52 与雷达/保险杠口径对齐。

用法：python3 ai/tools/test_macan_sng_params.py
"""
import sys
import types

sys.path.insert(0, '/data/openpilot')

import openpilot.cereal.messaging as messaging
from openpilot.selfdrive.car.helpers import convert_carControlSP
from openpilot.sunnypilot.selfdrive.controls.controlsd_ext import ControlsExt

PASS = 0
FAIL = 0


def check(name, cond, detail=""):
  global PASS, FAIL
  if cond:
    PASS += 1
    print(f"  ✅ {name}")
  else:
    FAIL += 1
    print(f"  ❌ {name}  {detail}")


def make_sm(prob=None, x=None, v=None, n_leads=1):
  """最小 sm：真实 capnp 消息（radarState/selfdriveStateSP/accelerometer/longitudinalPlan/modelV2）。"""
  sm = {
    'radarState': messaging.new_message('radarState').radarState,
    'selfdriveStateSP': messaging.new_message('selfdriveStateSP').selfdriveStateSP,
    'accelerometer': messaging.new_message('accelerometer').accelerometer,
    'longitudinalPlan': messaging.new_message('longitudinalPlan').longitudinalPlan,
  }
  mv = messaging.new_message('modelV2')
  if n_leads:
    mv.modelV2.init('leadsV3', n_leads)
    for i in range(n_leads):
      mv.modelV2.leadsV3[i].init('x', 1)
      mv.modelV2.leadsV3[i].init('v', 1)
      mv.modelV2.leadsV3[i].x = [x[i]]
      mv.modelV2.leadsV3[i].v = [v[i]]
      mv.modelV2.leadsV3[i].prob = prob[i]
  sm['modelV2'] = mv.modelV2
  sm['longitudinalPlan'].aTarget = 0.31
  return sm


def params_of(cc):
  return {p.key: p.value.decode() for p in cc.params}


def run():
  me = types.SimpleNamespace(get_lead_data=lambda *a, **k: None)
  print("=" * 70)
  print("Macan SnG 视觉源通道（CC_SP.params / visLeadDist）冒烟测试")
  print("=" * 70)

  print("\n【1】原始视觉前车 → 参数（leadsV3[0].x − 1.52）")
  cc = ControlsExt.state_control_ext(me, make_sm(prob=[0.9], x=[7.61], v=[0.0]))
  prm = params_of(cc)
  check("seg9 视觉值：x=7.61 → visLeadDist=6.09，vLead=0.00",
        prm == {'visLeadDist': '6.09', 'visLeadVLead': '0.00'}, f"got {prm}")
  cc = ControlsExt.state_control_ext(me, make_sm(prob=[0.9], x=[13.52], v=[1.42]))
  prm = params_of(cc)
  check("前车在动：x=13.52 → 12.00 m，vLead=1.42 m/s",
        abs(float(prm['visLeadDist']) - 12.0) < 0.02 and prm['visLeadVLead'] == '1.42', f"got {prm}")

  print("\n【2】无目标 / 模型未捕捉 → 不下发（carcontroller 侧走单侧兜底）")
  cc = ControlsExt.state_control_ext(me, make_sm(prob=[0.1], x=[7.61], v=[0.0]))
  check("prob=0.1（模型未确认）→ 无 visLeadDist 参数", len(cc.params) == 0, f"n={len(cc.params)}")
  cc = ControlsExt.state_control_ext(me, make_sm(n_leads=0))
  check("leadsV3 为空 → 无参数且不抛异常", len(cc.params) == 0, f"n={len(cc.params)}")
  cc = ControlsExt.state_control_ext(me, make_sm(prob=[0.9], x=[1.0], v=[0.0]))
  check("x−1.52 ≤ 0（目标在相机后方）→ 无参数", len(cc.params) == 0, f"n={len(cc.params)}")

  print("\n【3】多目标只用 leadsV3[0]")
  cc = ControlsExt.state_control_ext(me, make_sm(prob=[0.9, 0.9], x=[7.61, 40.0], v=[0.0, 0.0], n_leads=2))
  prm = params_of(cc)
  check("两条 lead → visLeadDist 取 [0]=6.09", abs(float(prm['visLeadDist']) - 6.09) < 0.02, f"got {prm}")

  print("\n【4】消费侧契约：capnp → convert_carControlSP → carcontroller 的 _p.get(\"key\")")
  msg = messaging.new_message('carControlSP')
  msg.carControlSP = ControlsExt.state_control_ext(me, make_sm(prob=[0.9], x=[7.61], v=[1.42]))
  conv = convert_carControlSP(msg.carControlSP.as_reader())
  found = {}
  for _p in conv.params:
    found[_p.get("key")] = float(_p.get("value").decode())
  check("carcontroller 能按 key/value 取到 visLeadDist/visLeadVLead",
        abs(found.get('visLeadDist', 0) - 6.09) < 0.02 and abs(found.get('visLeadVLead', 0) - 1.42) < 0.02,
        f"got {found}")

  print("\n【5】回归守卫：pycapnp 的 ListBuilder 无 append()（历史 aTarget/slopePct 静默失效根因）")
  cc_probe = messaging.new_message('carControlSP').carControlSP
  has_append = hasattr(cc_probe.params, 'append')
  check("确认 _DynamicListBuilder 无 append()（故必须整表赋值）", not has_append,
        "若此断言失败说明 pycapnp 已支持 append，可考虑恢复 append 写法")

  print("\n" + "=" * 70)
  print(f"结果：{PASS} 通过 / {FAIL} 失败")
  if FAIL:
    print("❌ 存在失败项，请检查实现！")
    sys.exit(1)
  print("🎉 SnG 视觉源通道正常（生产 → capnp → 消费 全链路）")
  print("=" * 70)


if __name__ == "__main__":
  run()
