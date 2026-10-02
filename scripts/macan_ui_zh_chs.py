#!/usr/bin/env python3
"""补齐 Macan 定制 UI 的简体中文（zh-CHS）词条，并同步 app.pot / app_en.po。

背景：Macan 品牌页（volkswagen.py）、EPS 页（eps_settings.py）、mici 开关页
（mici/.../toggles.py）新增的 tr()/tr_noop() 串只存在于源码，三个目录文件
（app.pot / app_en.po / app_zh-CHS.po）都没重跑过提取 —— 这些 msgid 在 zh-CHS 里
直接 MISSING，运行期回退英文（system/ui/lib/multilang.py 直读 .po，无需编译 .mo）。

策略（与 app_zh-CHS.po 既有 Macan 段风格一致）：
  - app_zh-CHS.po：补译文（只补简体，不动繁体 zh-CHT）
  - app.pot     ：补 msgid（msgstr 留空 = 待译）
  - app_en.po   ：补 msgid（msgstr = msgid，与文件 Macan 段既有写法一致）

条目用 msgid 唯一前缀匹配（英文原文从源码提取结果里取，避免手抄出错）。
用法：python3 ai/scripts/macan_ui_zh_chs.py [--dry-run]
"""
import argparse
import os
import sys
from pathlib import Path

BASEDIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASEDIR / "openpilot/selfdrive/ui/translations"))
import potools  # noqa: E402

UI_DIR = BASEDIR / "openpilot/selfdrive/ui"
TRANS = UI_DIR / "translations"

# 取词条来源（与 selfdrive/ui/translations/update_translations.py 的扫描范围一致）
def scan_files():
  roots = [
    BASEDIR / "openpilot/system/ui",
    UI_DIR / "widgets", UI_DIR / "layouts", UI_DIR / "onroad",
    UI_DIR / "sunnypilot", UI_DIR / "mici",
    BASEDIR / "openpilot/selfdrive/selfdrived",
    BASEDIR / "openpilot/sunnypilot/selfdrive/selfdrived",
  ]
  files = []
  for root in roots:
    for dp, _, fns in os.walk(root):
      files += [os.path.relpath(os.path.join(dp, fn), BASEDIR) for fn in fns if fn.endswith(".py")]
  return sorted(set(files))

# (msgid 唯一前缀, 简体译文)
POT_EN_ONLY = ["Yiser-J6"]  # 专有名词：只进模板/英文，不进简中

TRANSLATIONS = [
  # ── Macan 品牌页 / mici 开关页标题 ──────────────────────────────
  ("起步跟停（Stop and Go）",              "起步跟停（Stop and Go）"),
  ("Macan Stop and Go",                    "Macan 起步跟停"),
  ("Startup Safe Distance (Macan)",        "起步安全距离（Macan）"),
  ("Macan Accel Jerk Limit",               "Macan 加速度变化率限制"),
  ("Accel Jerk Limit (Macan)",             "加速度变化率限制（Macan）"),
  ("Accel Jerk Limit Value",               "加速度变化率限制值（m/s³）"),
  ("Macan Slope Compensation",             "Macan 坡度补偿"),
  ("Slope Compensation (Macan)",           "坡度补偿（Macan）"),
  ("Macan Slope Comp Unlimited",           "Macan 坡度补偿-放开限制"),
  ("Slope Comp Unlimited (Macan)",         "坡度补偿-放开限制（Macan）"),
  ("Macan Accel Deadzone Enable",          "Macan 加速度死区总开关"),
  ("Macan Accel Deadzone (m/s^2)",         "Macan 加速度死区（m/s²）"),
  ("Radar Fusion (Macan)",                 "雷达融合（Macan）"),
  ("Macan Verz Bridge",                    "Macan Verz 桥"),
  ("Macan Distance Sync Direction",        "Macan 跟车距离档同步方向"),
  ("Fusion Control Mode (Macan)",          "融合控制模式（Macan）"),
  # ── EPS 助力补偿页（Macan 专属） ────────────────────────────────
  ("EPS Assist Compensation",              "EPS 助力补偿"),
  ("EPS Compensation Scale",               "EPS 补偿系数"),
  ("Customize EPS Compensation",           "自定义 EPS 助力补偿"),
  # ── 其他 fork 定制串（非 Macan，但同属简中缺失） ────────────────
  ("Generic keyboard / HID",               "通用键盘 / HID"),
  ("Tap a cell to cycle actions",          "点按单元格可循环切换动作，然后保存。"),
  ("Testing...",                           "测试中…"),
  ("hours",                                "小时"),
  ("min",                                  "分钟"),
  # ── 说明文案（tr_noop，长文本） ─────────────────────────────────
  ("Macan Stop and Go:",
   "Macan 起步跟停：开启后由视觉模型判断起步时机，openpilot 发送 RESUME 信号解除原厂驻车保持"
   "（伴随提示音）。关闭时需轻踩油门或按 SET/RESUME 起步（原厂行为）。"),

  ("Startup Safe Distance (Macan):",
   "起步安全距离（Macan）：开启后，自动从静止起步需要原厂雷达距离（>0）或视觉前车（>5m）——"
   "防止误起步。关闭时仅凭视觉意图起步（V1 行为）——拥堵时使用可保持紧跟前车、防止加塞。"
   "仅在“起步跟停（Macan）”开启时有效。"),

  ("Macan Accel Jerk Limit:",
   "Macan 加速度变化率限制：限制加速度请求的变化快慢（m/s³）。越低越平顺（过渡更柔和、顿挫更少），"
   "越高响应越快。0 = 关闭（不限）。出于安全，减速（刹车）允许 2.2 倍的更快变化。1 秒内生效。"),

  ("Macan Slope Compensation:",
   "Macan 坡度补偿：开启后，IMU 坡度信号把 g*sin(坡度) 叠加到加速度请求上——上坡发正 Verz 请求"
   "（加速声明，约 4.2*sin(坡度)）以增加扭矩；用油门覆盖减速时先发 180ms 的 +1.285 正 Verz 斜坡；"
   "下坡轻点刹车（防前窜）。默认关闭 = 原厂行为。切换后建议重启 onroad 循环。"),

  ("Macan Slope Comp Unlimited (sub-option)",
   "Macan 坡度补偿-放开限制（子选项）：坡度补偿开启时，取消原厂力矩上限"
   "（选项2：min(max(stock_mom, 200))），让缓坡也能起效。关闭时按原厂上限（选项1：min(stock_mom)）。"),

  ("Macan Accel Deadzone Enable:",
   "Macan 加速度死区总开关。关闭 = 死区完全失效（数值保留但不生效）。"),

  ("Macan Accel Deadzone:",
   "Macan 加速度死区：aTarget 在 ±该值以内归零，滤除 MPC 抖动（m/s²）。0 = 关闭。"),

  ("Radar Fusion (Macan):",
   "雷达融合（Macan）：使用原厂 ACC 雷达（bus2 距离 + 前车速度）修正视觉前车，减少跟车抖动。"),

  ("Macan Verz Bridge:",
   "Macan Verz 桥：开启后，桥接逻辑按百分比斜坡平滑减速请求（步进 = 1.25% × |verz|）——"
   "缓和 OP 发起的急减速，消除喘息/脉冲。关闭时 verz 请求原样直通（一步到位，无斜坡）。"
   "出于安全，深度刹车（<= -1.5）与原厂刹车请求无论开关都直通。"),

  ("ON: openpilot style wins",
   "开：以 openpilot 为准——点火后发送 DIST ± 脉冲，让原厂 ACC 跟随你记忆的档位"
   "（例如 4 格 = 舒适）。关：以车为准——openpilot 把档位重置为车辆默认（3 格 = 标准）。"
   "仅 Macan 生效。"),

  ("ON: fusion control",
   "开：融合控制——OP 纵向接管，原厂 ACC 雷达保持激活并约束刹车。关：纯 OP 纵向——"
   "原厂 ACC 雷达停用（LS_01 bus2 保持待机），ACC02/04/05 完全由 OP 自行生成。"),

  ("Compensate for the EPS speed-dependent",
   "补偿 EPS 随速助力曲线（低速时 EPS 会吸收部分转向指令）。关闭后可与原厂转向手感对比。"),

  ("Compensation amount: 1.00",
   "补偿强度：1.00 = 完整 MQB 曲线（低速 ×1.6），0.50 = 一半。"
   "警告：0.00 会使转向输出归零——请改用上方开关关闭。"),
]


def quote(s: str) -> str:
  assert "\n" not in s, f"multi-line string not supported: {s!r}"
  return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t") + '"'


def ref_line(source_ref: str) -> str:
  """源码引用只留文件名（测试禁止带行号）；分隔符沿用目录文件既有的反斜杠风格。"""
  path = source_ref.rsplit(":", 1)[0]
  return "#: " + path.replace("/", "\\")


def resolve(source_ids, key: str) -> str:
  if key in source_ids:
    return key
  hits = sorted(m for m in source_ids if m.startswith(key))
  assert len(hits) == 1, f"prefix {key!r} matched {len(hits)} msgid(s): {hits[:3]}"
  return hits[0]


def append_entries(path: Path, rows, dry_run: bool) -> int:
  if not rows:
    return 0
  text = path.read_text(encoding="utf-8")
  for msgid, msgstr, ref in rows:
    block = f"{ref}\nmsgid {quote(msgid)}\nmsgstr {quote(msgstr)}\n\n"
    text = text.rstrip("\n") + "\n\n" + block
  if not dry_run:
    path.write_text(text, encoding="utf-8")
  return len(rows)


def drop_orphan_entry(path: Path, needle: str, dry_run: bool) -> int:
  """删掉 msgid 已不在源码里的陈旧条目（按行定位，不整文件重写，避免 ref 风格翻车）。"""
  lines = path.read_text(encoding="utf-8").split("\n")
  hits = [i for i, l in enumerate(lines) if l.startswith("msgid ") and needle in l]
  assert len(hits) <= 1, f"ambiguous orphan needle {needle!r}: {len(hits)} hits"
  if not hits:
    return 0
  i = hits[0]
  start = i
  while start > 0 and (lines[start - 1].startswith("#") or lines[start - 1].startswith('"')):
    start -= 1
  end = i
  while end + 1 < len(lines) and (lines[end + 1].startswith("msgstr") or lines[end + 1].startswith('"')):
    end += 1
  del lines[start:end + 1]
  if start < len(lines) and lines[start] == "":
    del lines[start]
  if not dry_run:
    path.write_text("\n".join(lines), encoding="utf-8")
  return 1
FONT_PATH = BASEDIR / "openpilot/selfdrive/assets/fonts/OpFont-Regular.otf"


def check_glyph_coverage(pairs) -> None:
  """简中 UI 走 OpFont-Regular.otf；字体没这个字形就会渲染成方块，提交前必须拦下。

  踩过的坑：≤(U+2264) 与 帧(U+5E27) 都不在 OpFont 里（raylib 启动日志会打
  "Requested codepoints glyphs found: [951/959]"），译文里用了就会显示豆腐块。
  """
  try:
    from fontTools.ttLib import TTFont
  except ImportError:
    print("glyph check skipped: no fontTools")
    return
  if not FONT_PATH.exists():
    print(f"glyph check skipped: {FONT_PATH} missing")
    return
  cmap = TTFont(str(FONT_PATH), fontNumber=0).getBestCmap()
  bad = [(ch, zh) for _, zh in pairs for ch in zh if ord(ch) not in cmap]
  for ch, zh in bad:
    print(f"  MISSING GLYPH U+{ord(ch):04X} {ch!r} in {zh[:60]!r}")
  assert not bad, f"{len(bad)} 个字形缺失，换字后重试"
  print(f"glyph coverage OK ({FONT_PATH.name}, {len(cmap)} glyphs)")


def main():
  ap = argparse.ArgumentParser()
  ap.add_argument("--dry-run", action="store_true")
  args = ap.parse_args()

  entries = potools.extract_strings(scan_files(), str(BASEDIR))
  source_ids = {e.msgid for e in entries}
  refs = {e.msgid: e.source_refs[0] for e in entries}
  print(f"source msgids: {len(source_ids)}")

  chs_path, pot_path, en_path = TRANS / "app_zh-CHS.po", TRANS / "app.pot", TRANS / "app_en.po"
  _, chs = potools.parse_po(chs_path)
  _, pot = potools.parse_po(pot_path)
  _, en = potools.parse_po(en_path)
  have_chs, have_pot, have_en = ({e.msgid for e in p} for p in (chs, pot, en))

  resolved = []
  for key, zh in TRANSLATIONS:
    msgid = resolve(source_ids, key)
    assert msgid not in have_chs, f"already translated, drop from list: {msgid!r}"
    resolved.append((msgid, zh))
  ids = [m for m, _ in resolved]
  assert len(set(ids)) == len(ids), "duplicate msgid resolved from TRANSLATIONS"

  # 专有名词：只补模板/英文，简中保持原文（回退英文）
  extra = [resolve(source_ids, k) for k in POT_EN_ONLY]

  check_glyph_coverage(resolved)

  chs_rows = [(m, s, ref_line(refs[m])) for m, s in resolved]
  pot_rows = [(m, "", ref_line(refs[m])) for m, _ in resolved + [(x, "") for x in extra] if m not in have_pot]
  en_rows = [(m, m, ref_line(refs[m])) for m, _ in resolved + [(x, "") for x in extra] if m not in have_en]

  n_chs = append_entries(chs_path, chs_rows, args.dry_run)
  n_pot = append_entries(pot_path, pot_rows, args.dry_run)
  n_en = append_entries(en_path, en_rows, args.dry_run)
  n_drop = drop_orphan_entry(en_path, "(current mode)", args.dry_run)

  print(f"zh-CHS +{n_chs} | pot +{n_pot} | en +{n_en} | en stale removed {n_drop}"
        f"{'   [DRY RUN]' if args.dry_run else ''}")


if __name__ == "__main__":
  main()
