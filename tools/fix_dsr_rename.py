#!/usr/bin/env python3
"""一次性完成：
1. 系统性修复 po 条目间缺空行（multilang 靠空行 finish()，缺空行→条目被覆盖吞掉→显示英文）
2. Macan 转向系数开关改名 Dynamic Steering Ratio（sp 标题+描述、mici 标题，英文源码）
3. po 加新条目中文翻译（zh-CHS/zh-CHT）
"""
import re, sys

PO_FILES = [
    "openpilot/selfdrive/ui/translations/app_zh-CHS.po",
    "openpilot/selfdrive/ui/translations/app_zh-CHT.po",
]

# ============ 1. 修复 po 条目间缺空行 ============
print("=== 1. po 空行修复 ===")
for pf in PO_FILES:
    lines = open(pf, encoding="utf-8").read().split("\n")
    out = []
    seen_msgstr = False  # 当前条目已读到 msgstr（未 finish）
    fixed = 0
    for line in lines:
        s = line.strip()
        if not s:
            seen_msgstr = False
            out.append(line)
            continue
        if s.startswith("#"):
            out.append(line)
            continue
        if s.startswith("msgid "):
            if seen_msgstr:
                out.append("")  # 补空行
                fixed += 1
                seen_msgstr = False
            out.append(line)
            continue
        if s.startswith("msgstr"):
            seen_msgstr = True
            out.append(line)
            continue
        if s.startswith('"'):
            out.append(line)
            continue
        out.append(line)
    open(pf, "w", encoding="utf-8").write("\n".join(out))
    print(f"  {pf.split('/')[-1]}: 修复 {fixed} 处缺空行")

# ============ 2. 改名 sp（volkswagen.py）============
print("\n=== 2. sp 改名 ===")
vf = "openpilot/selfdrive/ui/sunnypilot/layouts/settings/vehicle/brands/volkswagen.py"
s = open(vf, encoding="utf-8").read()

old_title = 'tr("Steering Params (Macan)")'
new_title = 'tr("Dynamic Steering Ratio (Macan)")'
assert old_title in s, "标题字符串未找到"
s = s.replace(old_title, new_title, 1)
print("  标题: Steering Params (Macan) → Dynamic Steering Ratio (Macan)")

old_desc_pat = re.compile(
    r"'Macan Steering Params \(experimental\): when enabled, uses calibrated '[\s\S]*?"
    r"'so this is EXPERIMENTAL - keep off until field data confirms.'"
)
new_desc_py = (
    "'Dynamic Steering Ratio (Macan): speed-dependent steering ratio - 15.0 below 140 km/h, '\n"
    "'18.7 above 145 km/h (linear transition 140-145), fitted from 29,284 samples across '\n"
    "'the full 4f route (RMSE 1.75 deg), plus torque friction 0.52. When disabled, uses '\n"
    "'stock fixed 16.2. Replaces the old experimental 18.0 (discarded: 22% gyro spread, '\n"
    "'15% oversteer in city corners).'"
)
s2, n = old_desc_pat.subn(new_desc_py, s)
assert n == 1, f"描述块未匹配（n={n}）"
s = s2
print("  描述: 更新为动态转向比说明")
open(vf, "w", encoding="utf-8").write(s)

# ============ 3. 改名 mici（toggles.py）============
print("\n=== 3. mici 改名 ===")
tf = "openpilot/selfdrive/ui/mici/layouts/settings/toggles.py"
t = open(tf, encoding="utf-8").read()
old_mici = 'tr("Macan Steering Params")'
new_mici = 'tr("Macan Dynamic Steering Ratio")'
assert old_mici in t, "mici 标题未找到"
t = t.replace(old_mici, new_mici, 1)
open(tf, "w", encoding="utf-8").write(t)
print("  mici: Macan Steering Params → Macan Dynamic Steering Ratio")

# ============ 4. po 加新条目 ============
print("\n=== 4. po 新条目 ===")
DESC = ("Dynamic Steering Ratio (Macan): speed-dependent steering ratio - 15.0 below 140 km/h, "
        "18.7 above 145 km/h (linear transition 140-145), fitted from 29,284 samples across "
        "the full 4f route (RMSE 1.75 deg), plus torque friction 0.52. When disabled, uses "
        "stock fixed 16.2. Replaces the old experimental 18.0 (discarded: 22% gyro spread, "
        "15% oversteer in city corners).")

TRANS = {
    "app_zh-CHS.po": {
        "anchor": 'msgstr "转向系数（Macan）"',
        "items": {
            "Dynamic Steering Ratio (Macan)": "动态转向比（Macan）",
            DESC: "Macan 动态转向比：速度相关转向比——低于140km/h用15.0，高于145km/h用18.7（140-145线性过渡），基于4f全段29284样本拟合（RMSE 1.75°），附带扭矩摩擦补偿0.52。关闭时使用原厂固定16.2。取代旧实验值18.0（已弃用：gyro极差22%，城市弯转向不足15%）。",
            "Macan Dynamic Steering Ratio": "Macan 动态转向比",
        },
    },
    "app_zh-CHT.po": {
        "anchor": 'msgstr "轉向係數（Macan）"',
        "items": {
            "Dynamic Steering Ratio (Macan)": "動態轉向比（Macan）",
            DESC: "Macan 動態轉向比：速度相關轉向比——低於140km/h用15.0，高於145km/h用18.7（140-145線性過渡），基於4f全段29284樣本擬合（RMSE 1.75°），附帶扭力摩擦補償0.52。關閉時使用原廠固定16.2。取代舊實驗值18.0（已棄用：gyro極差22%，城市彎轉向不足15%）。",
            "Macan Dynamic Steering Ratio": "Macan 動態轉向比",
        },
    },
}

for pf in PO_FILES:
    fn = pf.split("/")[-1]
    cfg = TRANS[fn]
    s = open(pf, encoding="utf-8").read()
    # 检查是否已存在
    if 'msgid "Dynamic Steering Ratio (Macan)"' in s:
        print(f"  {fn}: 已存在，跳过")
        continue
    assert cfg["anchor"] in s, f"{fn}: 锚点 {cfg['anchor']} 未找到"
    block = "\n".join(f'msgid "{k}"\nmsgstr "{v}"' for k, v in cfg["items"].items())
    s = s.replace(cfg["anchor"], cfg["anchor"] + "\n\n" + block, 1)
    open(pf, "w", encoding="utf-8").write(s)
    print(f"  {fn}: +{len(cfg['items'])} 条（插在旧条目后）")

# ============ 5. 验证 ============
print("\n=== 5. 验证（multilang 真实解析） ===")
sys.path.insert(0, "/data/openpilot")
from openpilot.system.ui.lib.multilang import load_translations
from pathlib import Path

all_ok = True
for pf in PO_FILES:
    fn = pf.split("/")[-1]
    trs, plur = load_translations(Path(pf))
    # 5a. Auto Lane Change 修复验证
    alc = "Auto Lane Change: Delay with Blind Spot" in trs
    # 5b. 新开关条目
    new_ok = all(k in trs for k in ["Dynamic Steering Ratio (Macan)", DESC, "Macan Dynamic Steering Ratio"])
    # 5c. 邻条目未破坏
    brd = "Block Lane Change: Road Edge Detection" in trs
    print(f"  {fn}: 总条目={len(trs)} | AutoLaneChange={'✅' if alc else '❌'} | "
          f"新开关3条={'✅' if new_ok else '❌'} | 道路边缘={'✅' if brd else '❌'}")
    if alc:
        print(f"      AutoLaneChange 中文: {trs['Auto Lane Change: Delay with Blind Spot']}")
    all_ok &= alc and new_ok and brd

print("\n✅ 全部通过" if all_ok else "\n❌ 有失败，需检查")
