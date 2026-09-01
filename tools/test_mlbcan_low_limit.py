#!/usr/bin/env python3
"""方案A低速min限制单测（2026-09-02 收回低速豁免）
断言：低速(v<=3.0)强制min(stock)（unlimited不放开）；高速维持现状；stock=0安全阀。
预置 _last_acc_moment=999 绕过+8斜坡，直接得无斜坡原始值。
"""
import sys
sys.path.insert(0, '/data/openpilot')
sys.path.insert(0, '/data/openpilot/opendbc_repo')
from unittest import mock
from opendbc.car.volkswagen import mlbcan
from opendbc.car.volkswagen.mlbcan import create_acc_accel_control

def run(v_ego, stock_mom, accel, unlimited, slope_comp=True):
    mlbcan._last_acc_moment = 999.0  # 绕过斜坡
    packer = mock.MagicMock()
    packer.make_can_msg.return_value = (0x10D, b'\x00'*8, 2)
    create_acc_accel_control(packer=packer, bus=2, acc_type=1, acc_enabled=True,
                             accel=accel, acc_control=3, stopping=False, starting=False,
                             esp_hold=False, v_ego=v_ego, stock_mom=stock_mom,
                             slope_pct=0.0, slope_comp=slope_comp,
                             slope_comp_unlimited=unlimited)
    return packer.make_can_msg.call_args[0][2]['ACC_Momentenanforderung']

ok = 0; fail = 0
def chk(name, got, want, tol=1.0):
    global ok, fail
    if abs(got - want) <= tol:
        ok += 1; print(f"  ✅ {name}: {got} == {want}")
    else:
        fail += 1; print(f"  ❌ {name}: {got} != {want}")

print("【低速段 v=2.0（核心：unlimited开也被min到stock）】")
chk("低速+unlimited开+accel0.5 → min(69.7,50)=50", run(2.0, 50, 0.5, True), 50)
chk("低速+unlimited关+accel0.5 → 50", run(2.0, 50, 0.5, False), 50)

print("【高速段 v=5.0（维持现状：unlimited影响生效）】")
chk("高速+unlimited开+accel2.0 → 200上限", run(5.0, 50, 2.0, True), 200)
chk("高速+unlimited关+accel2.0 → min(214,50)=50", run(5.0, 50, 2.0, False), 50)

print("【安全阀 stock_mom=0（不限制，OP自由）】")
chk("低速+stock=0+accel0.5 → 69.7不受限", run(2.0, 0, 0.5, True), 69.7)
chk("高速+stock=0+accel2.0 → 214.6不受限", run(5.0, 0, 2.0, False), 214.5)

print(f"\n结果: {ok} 通过 / {fail} 失败")
sys.exit(1 if fail else 0)
