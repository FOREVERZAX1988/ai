#!/usr/bin/env python3
"""合并回归清单：上游重构造成「静默断链」的定点复核。

为什么需要它：`sim_test_macan.py` 跑的是行为回归（车型接口、cruise、按键、
纵向帧级），而这类问题**根本不改行为语义** —— 上游改了契约，我们的调用点还在
用旧名字，表现是 import 炸、启动崩、或者某个参数键在所有进程里 UnknownKeyName。
它们要么被 boot_smoke 的 import 扫到（但只报「某个模块失败」，不说为什么），
要么要跑到很深的用例才暴露（vehicleParameters 就是跑到纵向测试才 KeyError）。

每条断言都对应 2026-10-29 那次合并里真实踩到的故障，note 记着当时的现象。

用法：
  python ai/tools/merge_regression_check.py          # 默认从脚本位置推仓库根
  OPENPILOT_ROOT=/data/openpilot python ai/tools/merge_regression_check.py
退出码：0 全过；1 有回归
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("OPENPILOT_ROOT") or Path(__file__).resolve().parents[2])

CHECKS: list[tuple[str, str, object]] = []


def check(name: str, note: str):
  def deco(fn):
    CHECKS.append((name, note, fn))
    return fn
  return deco


def text(rel: str) -> str:
  p = ROOT / rel
  if not p.exists():
    raise AssertionError(f"文件不存在: {rel}")
  return p.read_text(encoding="utf-8", errors="replace")


def code_only(s: str) -> str:
  """去掉整行注释。

  检查「代码里还有没有旧写法」之前必须先过一遍：这些文件的注释里就写着
  「别再这么写」的反面示例（本文件第一版没排除注释，被自己的说明文字判成
  回归，白响一次警报）。只去掉 # 开头的行，够用且不会误伤字符串里的 #。
  """
  return "\n".join(l for l in s.splitlines() if not l.lstrip().startswith("#"))


# ── 1. 上游把 API_HOST 常量换成了 get_api_host() 函数 ──────────────────────────
@check("A1 api: 不再导入 API_HOST，改用 get_api_host()",
       "旧写法 `from ...comma_connect import API_HOST` 会 ImportError；navd 的 mapbox_host 拼接也跟着改")
def _api_host():
  init = code_only(text("openpilot/common/api/__init__.py"))
  assert not re.search(r"^\s*from\s+openpilot\.common\.api\.comma_connect\s+import\s+.*\bAPI_HOST\b",
                       init, re.M), "common/api/__init__.py 仍在导入 API_HOST"
  navd = code_only(text("openpilot/selfdrive/navigation/navd.py"))
  assert "get_api_host" in navd, "navd.py 没有用 get_api_host()"


# ── 2. 上游把 system.hardware（提供 TICI）并到 common.hardware（只有 HARDWARE/PC）──
@check("A2 hardware: TICI 由 HARDWARE.get_device_type() 自行推导",
       "`from openpilot.system.hardware import TICI` 已不存在；cluster 这两处会 ImportError，集群 UI 起不来")
def _tici():
  pat = re.compile(r"TICI\s*=\s*not\s+PC\s+and\s+HARDWARE\.get_device_type\(\)\s+in\s+\(?['\"]tici['\"]")
  for rel in ("openpilot/sunnypilot/carrot/cluster_autorun.py",
              "openpilot/sunnypilot/carrot/cluster/main.py"):
    s = text(rel)
    assert pat.search(s), f"{rel} 没有重新推导 TICI"
    assert "from openpilot.system.hardware import" not in s or "TICI" not in s.split("import", 1)[1][:80], \
      f"{rel} 仍在从 openpilot.system.hardware 导入 TICI"


# ── 3. plant.py 不再制造 vehicleParameters，但 longitudinal_planner 仍读它 ──────
@check("A3 plant: 仿真 plant 仍发 vehicleParameters 消息",
       "上游删掉这条消息后，longitudinal_planner 读 sm['vehicleParameters'].angleOffsetDeg 直接 KeyError，纵向用例全挂")
def _vehicle_parameters():
  s = code_only(text("openpilot/selfdrive/test/longitudinal_maneuvers/plant.py"))
  assert "new_message('vehicleParameters')" in s, "plant.py 不再构造 vehicleParameters"
  assert "'vehicleParameters':" in s, "PlannerSM 里没有塞 vehicleParameters"


# ── 4. manager.py 的 model_dir 曾被注释行吞掉（合并时注释跨行） ─────────────────
@check("A4 manager: clear_model_cache 里 model_dir 是独立赋值语句",
       "被并进注释后是 F821/NameError，只在清缓存那条路径上炸，import 阶段看不出来")
def _model_dir():
  s = text("openpilot/sunnypilot/models/manager.py")
  m = re.search(r"def clear_model_cache.*?(?=\ndef |\Z)", s, re.S)
  assert m, "找不到 clear_model_cache"
  body = m.group(0)
  assert re.search(r"^\s{2,}model_dir\s*=\s*Paths\.model_root\(\)\s*$", body, re.M), \
    "model_dir 不是独立语句（被注释吞掉了）"


# ── 5. 参数键表是编译期 ABI：头文件里有、二进制里没有 -> UnknownKeyName ──────────
@check("A5 params: 4 个蓝牙键 + TestAlert 已登记在 params_keys.h",
       "只改 header 不重建 libparams，所有进程在新键上 UnknownKeyName 崩；这几个键是合并时补的")
def _param_keys():
  s = text("openpilot/common/params_keys.h")
  for k in ("BluetoothEnabled", "BluetoothAudioAddress", "BluetoothAudioTestActive",
            "BluetoothDisconnectControllersOffroad", "TestAlert"):
    assert f'"{k}"' in s, f"params_keys.h 缺少 {k}"


# ── 6. alert 文案要能被 potools 提取（f-string 拼出来的抓不到） ─────────────────
@check("A6 i18n: 实验模式切换提示用两条 tr_noop 静态串",
       "f\"实验模式已{'开启' if ... else '关闭'}\" 提取器只能看到碎片，非中文 UI 永远显示源文案")
def _alert_tr_noop():
  s = code_only(text("openpilot/sunnypilot/selfdrive/selfdrived/events.py"))
  assert 'tr_noop("实验模式已开启")' in s and 'tr_noop("实验模式已关闭")' in s, \
    "events.py 的实验模式提示没有拆成两条 tr_noop"
  assert 'f"实验模式已{' not in s, "还在用 f-string 拼 alert 文案"


# ── 7. 测试要断言 callback 的真实契约（源文案），不是 po 里的英文 ───────────────
@check("A7 test: selfdrived 的 alert 断言的是源文案",
       "上游测试断言 'Experimental Off'，该串全仓不存在（翻译在 alert_renderer 的 tr() 里做），必红")
def _alert_test():
  s = code_only(text("openpilot/sunnypilot/selfdrive/selfdrived/tests/test_selfdrived_zp.py"))
  assert "实验模式已关闭" in s, "测试没断言源文案"
  assert "Experimental Off" not in s, "测试仍在断言英文串"


# ── 8. 测试之间不能靠 sys.modules stub 互相污染 ────────────────────────────────
@check("A8 test: test_git_proxy 只在真模块不可用时才 stub swaglog",
       "无条件往 sys.modules 塞 types.ModuleType（无 __file__），隔壁 manager.py 的 "
       "`from ...swaglog import add_file_handler` 在收集阶段就 ImportError")
def _swaglog_stub():
  s = code_only(text("openpilot/sunnypilot/system/updated/tests/test_git_proxy.py"))
  assert re.search(r"try:\s*\n\s+import openpilot\.common\.swaglog", s), \
    "没有先尝试导入真模块（无条件 stub 会污染同目录其它测试）"
  assert "stub.add_file_handler" in s, "stub 缺 add_file_handler"


# ── 9. 没装 git-lfs 的机器要用 file_chunker，不能把 LFS 指针当真文件 ────────────
@check("A9 build: build_stripped.sh 按 git-lfs 是否存在分流",
       "无 lfs 时 setup_lfs.sh 会把指针文件留在产物里，设备上模型加载直接失败")
def _build_stripped():
  s = code_only(text("tools/release/build_stripped.sh"))
  # 负向前瞻不能省：单纯 `in` 判断会被 `git-lfs-disabled` 这类东西骗过去
  # （本清单第一版就这么漏掉了自己注入的故障）。
  assert re.search(r"command -v\s+git-lfs(?![-\w])", s), "没有探测 git-lfs"
  assert "setup_lfs.sh" in s, "缺少 git-lfs 分支"
  assert "file_chunker" in s, "缺少 file_chunker 兜底分支"


# ── 10. 左侧 HUD 几何只能有一个来源（实车重叠就出在这） ────────────────────────
@check("A10 ui: speed_limit 只用 hud_left_row_rects() 算几何",
       "上游的 CarrotPanelSide 手写分支在 2026-10-04 实车上让限速牌和速度重叠")
def _speed_limit():
  s = code_only(text("openpilot/selfdrive/ui/sunnypilot/onroad/speed_limit.py"))
  assert "hud_left_row_rects" in s, "没有用 hud_left_row_rects"


# ── 11. 上游 _online_cores() 引用了未导入的 get_available_cores（F821） ──────────
@check("A11 ui: ui.py 不残留上游的 _online_cores()",
       "它引用的 get_available_cores 本文件没导入，留着就是 F821；我们用 pick_online_core")
def _ui_cores():
  s = code_only(text("openpilot/selfdrive/ui/ui.py"))
  assert "_online_cores" not in s, "ui.py 还残留 _online_cores()"
  assert "pick_online_core" in s, "ui.py 没有用 pick_online_core"


# ── 12. jetlink 的 QNN 必须走「按路径 RTLD_GLOBAL 打开」那套 ────────────────────
@check("A12 jetlink: Bridge.swift 保留按路径装载 + 分号 ADSP_LIBRARY_PATH",
       "backend 按名字查找，不先按路径 RTLD_GLOBAL 打开同名库，NPU 静默拿不到节点")
def _jetlink_qnn():
  s = code_only(text("jetlink_repo/JetlinkKit/Sources/JetlinkAndroid/Bridge.swift"))
  assert "RTLD_GLOBAL" in s, "Bridge.swift 没有 RTLD_GLOBAL 装载"
  assert ";" in s, "Bridge.swift 没有分号拼接（ADSP_LIBRARY_PATH 要求）"
  assert "qnn_library_dir" in s or "qn" in s.lower(), "Bridge.swift 与 QNN 无关了？请人工确认"


# ── 13. 脚本执行位：git mode 错了就是 126，manager 每秒重启一次 ────────────────
@check("A13 perms: modeld 包装链路与 8 个脚本保持 100755",
       "2026-10-26 22:16-22:28 全部 9 段行程 modeld 从未运行：移植把 modeld.py 从 100755 改成 "
       "100644，包装脚本 exec 时 bash 返回 126。后果是 cameraState/liveCalibration 全缺，"
       "calibrationd 拿不到 cameraOdometry，校准进度恒 0（600/600 帧都是「校准进行中：0%」）")
def _exec_bits():
  import subprocess
  files = [
    "openpilot/common/hardware/comma/agnos.py",
    "openpilot/selfdrive/controls/radard.py",
    "openpilot/selfdrive/monitoring/dmonitoringd.py",
    "openpilot/selfdrive/pandad/pandad.py",
    "openpilot/selfdrive/selfdrived/events.py",
    "openpilot/selfdrive/selfdrived/selfdrived.py",
    "openpilot/selfdrive/ui/ui.py",
    "openpilot/sunnypilot/modeld_v2/modeld.py",
  ]
  out = subprocess.run(["git", "ls-files", "-s", "--", *files], cwd=str(ROOT),
                       capture_output=True, text=True).stdout
  seen = {}
  for line in out.splitlines():
    meta, path = line.split("\t", 1)
    seen[path] = meta.split()[0]
  bad = [(f, seen.get(f, "未跟踪")) for f in files if seen.get(f) != "100755"]
  assert not bad, f"这些文件不是 100755（exec 时装会 126）：{bad}"
  # 包装脚本本身也必须是可执行的，否则连 126 都到不了，直接 EACCES
  wrapper = ROOT / "openpilot/sunnypilot/modeld_v2/modeld"
  assert wrapper.is_file() and os.access(wrapper, os.X_OK), "modeld 包装脚本不存在或不可执行"


def main() -> int:
  print(f"仓库根: {ROOT}")
  print("=" * 72)
  failed = []
  for name, note, fn in CHECKS:
    try:
      fn()
    except AssertionError as e:
      failed.append((name, str(e), note))
      print(f"  ❌ {name}\n     {e}")
    except Exception as e:  # noqa: BLE001 - 检查本身写错也要报出来
      failed.append((name, f"{type(e).__name__}: {e}", note))
      print(f"  ❌ {name}\n     {type(e).__name__}: {e}")
    else:
      print(f"  ✅ {name}")

  print("=" * 72)
  print(f"结果：{len(CHECKS) - len(failed)} 通过 / {len(failed)} 失败")
  if failed:
    print("\n失败项的现象说明（避免下次重踩）：")
    for name, err, note in failed:
      print(f"  · {name}\n    {note}")
    return 1
  print("🎉 合并回归清单全部通过")
  return 0


@check("A14 agnos: agnos_init 里 --verify 必须排在 stock 跳过分支之前",
       "stock 分支先 return 的话，另一槽明明已刷好也不会切槽，只能去 WebUI 手动点一次。"
       "2026-10-29 的 mici 就卡在这：/VERSION=19.9、system_b=20.2-carrot-bt2 早已校验"
       "通过，开机却始终不 swap")
def _agnos_verify_order():
  s = code_only(text("launch_chffrplus.sh"))
  m = re.search(r"^agnos_init\(\)\s*\{", s, re.M)
  assert m, "找不到 agnos_init() 定义"
  body = s[m.end():]
  end = re.search(r"^\}", body, re.M)   # 顶格 } = 函数结束
  body = body[:end.start()] if end else body

  i_verify = body.find("--verify")
  assert i_verify >= 0, "agnos_init 里没有 --verify 调用：另一槽就绪也不会切槽"
  i_skip = body.find("AGNOS_SKIP_STOCK_FLASH")
  assert i_skip >= 0, "找不到 stock 跳过分支的开关 AGNOS_SKIP_STOCK_FLASH"
  assert i_verify < i_skip, (
    "--verify 被排到了 stock 跳过分支之后：stock 设备上另一槽即使已就绪也不会"
    "切槽，只能去 WebUI 手动点。把 --verify + reboot 提到跳过分支之前")


@check("A15 jetlink: mici 面板必须把 MODES 的每个模式都列出来",
       "面板只列 off/usb/ios 时，参数里存着的 wifi 匹配不上任何一项，控件按 0 读回，"
       "屏幕上显示 off 而链路其实是 Wi-Fi，再点一下还会把它覆盖成 usb。"
       "2026-10-30 在 mici 上发现：TestTheWifiMode 只断言了 LINK_MODE_LABELS 有 "
       "wifi 这个词，没断言面板真的给了这个选项，所以一直通过")
def _mici_jetlink_modes():
  p = "openpilot/selfdrive/ui/sunnypilot/mici/layouts/models.py"
  s = code_only(text(p))
  assert "link_toggle_options()" in s, f"{p} 不再调用 link_toggle_options()：模式的列表又以内联方式写了"
  m = re.search(r"^def link_toggle_options\(\).*?:\n(.*?)(?=^\S|\Z)", s, re.M | re.S)
  assert m, "找不到 link_toggle_options() 定义"
  fn = m.group(1)
  assert re.search(r'MODES\s*\]\s*,|for m in MODES', fn), (
    "link_toggle_options() 不再按 MODES 全量生成：少列一个模式就会让存着的那个值读回成 off")
  # 负向：任何形式的「把某个模式滤掉」都会重新引入这个 bug
  dropped = re.findall(r'if m != "(\w+)"|\bm not in \(', fn)
  assert not dropped, (
    f"link_toggle_options() 又把 {dropped} 滤掉了：取 hires panel 少列模式 -> 存着的值读回成 off")



@check("A16 ui: 每个设置面板都要能真的打开并渲染一遍",
       "AlphaLongitudinalToggles.update_state() 引用 __init__ 已不再创建的 _dec_toggle："
       "解冲突时 DEC 主开关的创建被上游的删除提交带走，引用留下了。"
       "现象是手指一点进 设置 → Cruise，整个 UI 抛 AttributeError 重启"
       "（2026-10-30 的 .79）。单看某个 layout 的渲染测试抓不到，"
       "必须走真实 SettingsLayout 逐面板 show_event + render")
def _settings_panels_render():
  import subprocess

  script = ROOT / "openpilot/selfdrive/ui/tests/settings_panels_render_smoke.py"
  assert script.exists(), f"找不到面板渲染冒烟测试: {script}"
  env = dict(os.environ)
  env["PYTHONPATH"] = os.pathsep.join(str(ROOT / p) for p in (".", "opendbc_repo", "msgq_repo", "rednose_repo"))
  try:
    r = subprocess.run([sys.executable, str(script)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
  except subprocess.TimeoutExpired:
    raise AssertionError("面板渲染冒烟测试超时（300s）")
  out = r.stdout + r.stderr
  if "FAILED" in out:
    bad = [l.strip() for l in out.splitlines() if l.strip().startswith(("FAIL", "- panel", "- ")) and "panel" in l]
    raise AssertionError("面板渲染失败，点进去就会崩 UI：\n     " + "\n     ".join(bad[:4] or out.strip().splitlines()[-4:]))
  if "PASSED" not in out:
    raise AssertionError(f"冒烟测试没跑起来（exit={r.returncode}）：\n     " + "\n     ".join(out.strip().splitlines()[-4:]))


@check("A17 ui: 设置面板引用的图标必须真的在 selfdrive/assets 里",
       "tizi 的 Toggles 面板给 Experimental Mode 行设 experimental.png / experimental_white.png，"
       "而这两个图早在图标搬去 sunnypilot/selfdrive/assets 时就不在 selfdrive/assets/icons 了。"
       "表现是打开该面板每次都在日志里刷 FILEIO Failed to open file + failed to load asset，"
       "那一行没有图标（2026-10-30 的 .79）")
def _settings_icons_exist():
  assets = ROOT / "openpilot/selfdrive/assets"

  def resolves(lit: str) -> Path:
    # ListItemSP.set_icon() 会给裸名字加 icons/ 前缀；settings.py 的 icon= 是相对 assets 的路径
    return Path(os.path.normpath(assets / (lit if "/" in lit else f"icons/{lit}")))

  missing = []
  toggles = code_only(text("openpilot/selfdrive/ui/layouts/settings/toggles.py"))
  for name in set(re.findall(r'"([\w.-]+\.png)"', toggles)):
    if not resolves(name).exists():
      missing.append(f"toggles.py: {name}")
  for lit in set(re.findall(r'icon="([^"]+\.png)"', text("openpilot/selfdrive/ui/sunnypilot/layouts/settings/settings.py"))):
    if not resolves(lit).exists():
      missing.append(f"settings.py: {lit}")
  assert not missing, "图标不在 selfdrive/assets 下，面板会画不出来：\n     " + "\n     ".join(sorted(missing))

if __name__ == "__main__":
  sys.exit(main())
