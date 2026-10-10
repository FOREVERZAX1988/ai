#!/usr/bin/env python3
"""
openpilot 上车前一致性预检（sim preflight）
===========================================
把「只有上车才会爆、纯逻辑仿真又测不出来」的启动类错误拉进仿真。这两条链
正是本机真实踩过的坑（2026-10-10 点火后 UI 报 "sunnypilot Unavailable"）：

  阶段 A 参数链 —— 实际故障：card 崩 `UnknownKeyName: b'ToyotaBrakeOnset'`
    A1 构建新鲜度：libparams_c.so 必须存在且比 params_keys.h 新
       （与 launch_chffrplus.sh ensure_params_build 同一判据。合并新增参数键后
        .so 过期 → card 抛 UnknownKeyName → selfdrived 起不来 → UI 提示不可用）
    A2 原生键表 ABI：编译好的 native lib 必须认识 params_keys.h 里的每一个键
    A3 键登记：源码里 Params 访问的字面量键都必须登记在 params_keys.h
       （A2/A3 在 .so 还是好的时候也能提前抓到「代码用了没登记的键」这一类）

  阶段 B 模型/推理链 —— 实际故障：modeld 崩 `TypeError: 'NoneType' object is not reversible`
    B1 产物齐备：活动 bundle 的 driving pkl（含分片 manifest）/ native modeld 二进制 /
       关键模块 import
    B2 反序列化冒烟（--model-load）：按 modeld_v2._init_combined 的真实调用序列
       load_oob → metadata → 建输入队列（崩溃发生点）。默认带内存护栏：预计占用
       超限直接 SKIP，不用「可能把设备 OOM 打挂」的代价换一条测试结果。

  阶段 C 运行时链（--runtime，设备上）
    C1 关键进程存活 + manager 单实例（多实例会导致重复拉起/卡 UI）
    C2 /data/community/crashes 自本次 manager 启动后是否又有新崩溃

用法：
  cd /data/openpilot && python3 ai/tools/sim_preflight.py
  cd /data/openpilot && python3 ai/tools/sim_preflight.py --runtime   # 上车后
  cd /data/openpilot && python3 ai/tools/sim_preflight.py --model-load --runtime
退出码：0 = 通过（含 WARN/SKIP，会显式列出）；1 = 有 FAIL
"""

from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
import time
from pathlib import Path

OPENPILOT_ROOT = Path("/data/openpilot")
COMMON_DIR = OPENPILOT_ROOT / "openpilot" / "common"
PARAMS_KEYS_H = COMMON_DIR / "params_keys.h"
PARAMS_SO = COMMON_DIR / "libparams_c.so"
NATIVE_MODELD = OPENPILOT_ROOT / "openpilot" / "sunnypilot" / "modeld_v2" / "modeld"
STOCK_PKL = OPENPILOT_ROOT / "openpilot" / "selfdrive" / "modeld" / "models" / "driving_tinygrad.pkl"
CRASH_DIR = Path("/data/community/crashes")

# A3 只扫本仓自有代码；上游 vendor 树不扫（它们随上游 pin 走）
SCAN_DIRS = (
  "openpilot/sunnypilot",
  "openpilot/selfdrive",
  "openpilot/system",
  "openpilot/common",
  "openpilot/tools",
)
PARAM_METHODS = {"get", "get_bool", "get_type", "get_default", "put", "put_bool", "check_key", "remove"}
KEY_DECL_RE = re.compile(r'^\s*\{\s*"([A-Za-z0-9_]+)"\s*,')
KEY_LITERAL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,}$")

# 形如 params.get("X") 但 X 不是参数键的已知例外。每加一条都要写明理由，
# 命中时按 WARN 打印（不静默吞掉）。
KNOWN_NONKEYS: dict[tuple[str, str], str] = {
  ("openpilot/selfdrive/ui/sunnypilot/mici/layouts/steering.py", "MazdaTjaButton"):
    "上游缺陷：mici UI 读了 MazdaTjaButton，但本仓和上游 upstream/test 的 params_keys.h 都没登记这个键"
    "（全仓仅这 2 处出现、无写入方）→ Mazda 上走到这行即 UnknownKeyName。非本车路径，属上游修",
}

# 关键进程：名称 -> 命令行匹配串
RUNTIME_PROCS = {
  "manager": "manager.py",
  "webuid": "webui.webuid",
  "ui": "openpilot.selfdrive.ui.ui",
  "selfdrived": "openpilot.selfdrive.selfdrived",
  "card": "openpilot.selfdrive.card",
  "modeld_v2": "openpilot/sunnypilot/modeld_v2",
}

PASS, WARN, FAIL, SKIP = "PASS", "WARN", "FAIL", "SKIP"
_RESULTS: list[tuple[str, str, str]] = []


def record(level: str, name: str, detail: str = "") -> None:
  _RESULTS.append((level, name, detail))
  icon = {PASS: "✅", WARN: "⚠️ ", FAIL: "❌", SKIP: "⏭️ "}[level]
  print(f"  {icon} [{level}] {name}" + (f"\n        {detail}" if detail else ""))


def mem_available_kb() -> int:
  try:
    with open("/proc/meminfo") as f:
      for line in f:
        if line.startswith("MemAvailable:"):
          return int(line.split()[1])
  except OSError:
    pass
  return 0


def read_params_keys() -> set[str]:
  keys = set()
  with open(PARAMS_KEYS_H) as f:
    for line in f:
      if (m := KEY_DECL_RE.match(line)):
        keys.add(m.group(1))
  return keys


# ---------------------------------------------------------------- 阶段 A

def check_params_build() -> bool:
  """A1：与 launch_chffrplus.sh ensure_params_build 同判据（.so 必须比头文件新）"""
  if not PARAMS_KEYS_H.is_file():
    record(FAIL, "A1 params 构建新鲜度", f"缺少 {PARAMS_KEYS_H}")
    return False
  if not PARAMS_SO.is_file():
    record(FAIL, "A1 params 构建新鲜度",
           f"缺少 {PARAMS_SO.name}：manager/UI 会退到 mock 模式，键表 ABI 无从校验")
    return False
  so_m, keys_m = PARAMS_SO.stat().st_mtime, PARAMS_KEYS_H.stat().st_mtime
  if so_m < keys_m:
    record(FAIL, "A1 params 构建新鲜度",
           "libparams_c.so 比 params_keys.h 旧 +%.1fh → 合并新增的键在 .so 里不存在，"
           "card 会抛 UnknownKeyName 导致 sunnypilot Unavailable（重编：launch_chffrplus.sh ensure_params_build）"
           % ((keys_m - so_m) / 3600))
    return False
  record(PASS, "A1 params 构建新鲜度",
         f".so 领先头文件 %.1fh（%s）" % ((so_m - keys_m) / 3600, time.strftime("%m-%d %H:%M", time.localtime(so_m))))
  return True


def check_native_key_abi(keys: set[str]) -> None:
  """A2：编译好的 native lib 必须认识每一个登记的键（复现 UnknownKeyName）"""
  sys.path.insert(0, str(OPENPILOT_ROOT))
  try:
    from openpilot.common import params as params_mod
  except Exception as e:
    record(FAIL, "A2 原生键表 ABI", f"import openpilot.common.params 失败：{type(e).__name__}: {e}")
    return
  if params_mod.lib is None:
    record(WARN, "A2 原生键表 ABI", "native lib 未加载（mock 模式）→ 键表 ABI 无法校验")
    return
  try:
    p = params_mod.Params()
  except Exception as e:
    record(FAIL, "A2 原生键表 ABI", f"Params() 构造失败：{type(e).__name__}: {e}")
    return
  unknown = []
  for k in sorted(keys):
    try:
      p.check_key(k)
    except Exception as e:
      unknown.append(f"{k}({type(e).__name__})")
  if unknown:
    record(FAIL, "A2 原生键表 ABI",
           f"{len(unknown)}/{len(keys)} 个键不被已编译的 libparams_c.so 认识 → 一旦被读取即 UnknownKeyName 崩溃："
           + ", ".join(unknown[:10]) + (" …" if len(unknown) > 10 else ""))
  else:
    record(PASS, "A2 原生键表 ABI", f"native lib 认识全部 {len(keys)} 个登记键")


def _iter_param_key_literals():
  for rel in SCAN_DIRS:
    root = OPENPILOT_ROOT / rel
    if not root.is_dir():
      continue
    for py in root.rglob("*.py"):
      if "__pycache__" in py.parts:
        continue
      try:
        tree = ast.parse(py.read_text(encoding="utf-8"))
      except (SyntaxError, UnicodeDecodeError, OSError):
        continue
      for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
          continue
        if node.func.attr not in PARAM_METHODS or not node.args:
          continue
        recv = ast.unparse(node.func.value).lower()
        if "param" not in recv:
          continue          # dict.get / os.environ.get 等一律不参与
        arg = node.args[0]
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and KEY_LITERAL_RE.match(arg.value):
          yield arg.value, py.relative_to(OPENPILOT_ROOT).as_posix(), node.lineno, arg.value != arg.value.lower()


def check_key_registration(keys: set[str]) -> None:
  """A3：代码里访问的字面量键必须已登记（.so 新鲜时也能提前抓）

  只把「含大写的字面量」当候选键：params_keys.h 里 0 个小写键，而 dict.get("key") /
  json 字段（"params"/"value"/"platform"）这类小写字面量会被 receiver 含 param 的写法
  误伤。跳过的部分照样打 WARN 列出来，不静默丢。
  """
  unknown, excepted, skipped = [], [], []
  for key, rel, lineno, has_upper in _iter_param_key_literals():
    if not has_upper:
      skipped.append(f"{rel}:{lineno} {key}")
      continue
    if key in keys:
      continue
    if (rel, key) in KNOWN_NONKEYS:
      excepted.append((rel, lineno, key))
      continue
    unknown.append(f"{rel}:{lineno} {key}")
  if unknown:
    record(FAIL, "A3 参数键登记覆盖率",
           f"{len(unknown)} 处访问的键未登记在 params_keys.h（读取即 UnknownKeyName）：" + "; ".join(unknown[:8]))
  else:
    record(PASS, "A3 参数键登记覆盖率", "源码中的 Params 字面量键全部已登记")
  if excepted:
    record(WARN, "A3 已知例外（逐条有理由，不是放行）",
           "; ".join(f"{rel}:{lineno} {key} —— {KNOWN_NONKEYS.get((rel, key), '')}" for rel, lineno, key in excepted))
  if skipped:
    record(WARN, "A3 疑似非键名字面量（已跳过，供人工过目）",
           f"{len(skipped)} 处（多为 dict/json 字段）：" + ", ".join(skipped[:6]) + (" …" if len(skipped) > 6 else ""))


# ---------------------------------------------------------------- 阶段 B

def resolve_driving_pkl() -> tuple[str | None, str]:
  """复现 modeld_v2._find_driving_pkl：COMBINED_MODEL_PKL > 活动 bundle/paths.model_root"""
  env_pkl = os.environ.get("COMBINED_MODEL_PKL")
  if env_pkl and _pkl_exists(env_pkl):
    return env_pkl, "COMBINED_MODEL_PKL"
  sys.path.insert(0, str(OPENPILOT_ROOT))
  try:
    from openpilot.common.hardware.hw import Paths
    from openpilot.sunnypilot.models.helpers import get_active_bundle
    bundle = get_active_bundle()
    if bundle is not None and bundle.models:
      path = os.path.join(Paths.model_root(), bundle.models[0].artifact.fileName)
      if _pkl_exists(path):
        return path, f"active bundle {bundle.internalName}"
  except Exception:
    pass
  if _pkl_exists(str(STOCK_PKL)):
    return str(STOCK_PKL), "stock bundle"
  return None, "未找到"


def _pkl_exists(path: str) -> bool:
  from openpilot.common.file_chunker import get_manifest_path
  return os.path.exists(path) or os.path.exists(get_manifest_path(path))


def check_model_artifacts() -> str | None:
  """B1：产物齐备 + 关键模块 import。返回解析到的 pkl 路径供 B2 用。"""
  sys.path.insert(0, str(OPENPILOT_ROOT))
  sys.path.insert(0, str(OPENPILOT_ROOT / "opendbc_repo"))
  mods = [
    "openpilot.selfdrive.modeld.helpers",
    "openpilot.selfdrive.modeld.compile_modeld",
    "openpilot.sunnypilot.modeld_v2.compile_modeld",
    "openpilot.sunnypilot.modeld_v2.helpers",
    "openpilot.sunnypilot.models.helpers",
  ]
  bad = []
  for m in mods:
    try:
      __import__(m)
    except Exception as e:
      bad.append(f"{m}: {type(e).__name__}: {e}")
  if bad:
    record(FAIL, "B1 modeld 关键模块 import", " | ".join(bad))
  else:
    record(PASS, "B1 modeld 关键模块 import", f"{len(mods)} 个模块 import 干净")

  pkl, src = resolve_driving_pkl()
  if pkl is None:
    record(SKIP, "B1 driving pkl 齐备", f"{src}：无 pkl（未下模型时属正常）")
  else:
    try:
      from openpilot.common.file_chunker import get_existing_chunks
      parts = get_existing_chunks(pkl)
      total = sum(os.path.getsize(p) for p in parts)
      record(PASS, "B1 driving pkl 齐备", f"{pkl}（{len(parts)} 分片, {total / 1e6:.0f}MB, 来源 {src}）")
    except Exception as e:
      record(FAIL, "B1 driving pkl 齐备", f"{pkl}: {type(e).__name__}: {e}")
      pkl = None

  if not NATIVE_MODELD.is_file():
    record(FAIL, "B1 native modeld 产物", f"缺少 {NATIVE_MODELD}（scons 没编出来 → 上车 modeld 起不来）")
  else:
    record(PASS, "B1 native modeld 产物", f"{NATIVE_MODELD.name} {NATIVE_MODELD.stat().st_size}B")
  return pkl


MODEL_LOAD_SNIPPET = r'''
import resource, sys
lim = int(sys.argv[1]); resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
sys.path.insert(0, "/data/openpilot"); sys.path.insert(0, "/data/openpilot/opendbc_repo")
from openpilot.common.file_chunker import open_file_chunked
from openpilot.sunnypilot.modeld_v2.helpers import load_oob
from openpilot.sunnypilot.modeld_v2.compile_modeld import derive_frame_skip, make_split_input_queues, make_supercombo_input_queues
pkl = sys.argv[2]
jits = load_oob(open_file_chunked(pkl))
metadata = jits["metadata"]
dev = "CPU"
if "run_model" in jits or "model" in metadata:
    mm = metadata.get("model", metadata)
    shapes = mm["input_shapes"]
    fs = derive_frame_skip({}, shapes)
    if "run_model" in jits:
        from openpilot.selfdrive.modeld.compile_modeld import make_input_queues, nv12_copy_size
        from openpilot.system.camerad.cameras.nv12_info import get_nv12_info
        info = get_nv12_info(1928, 1208)
        make_input_queues(shapes, fs, device=dev, frame_copy_size=nv12_copy_size(*info[:3]))
        path = "run_model+make_input_queues"
    else:
        make_supercombo_input_queues(shapes, fs, device=dev)
        path = "supercombo+make_supercombo_input_queues"
else:
    vision = metadata["vision"]
    policy_keys = [k for k in metadata if k not in ("vision", "warp_dev")]
    first = metadata[policy_keys[0]]
    fs = derive_frame_skip(vision["input_shapes"], first["input_shapes"])
    make_split_input_queues(vision["input_shapes"], first["input_shapes"], fs, device=dev)
    path = "split+make_split_input_queues"
print("LOADED jits=%s path=%s" % (",".join(sorted(jits)), path))
'''


def check_model_load(pkl: str | None, force: bool) -> None:
  """B2：按真实调用序列反序列化 + 建输入队列（复现 modeld 崩溃点）"""
  if pkl is None:
    record(SKIP, "B2 模型反序列化冒烟", "无 driving pkl，跳过")
    return
  from openpilot.common.file_chunker import get_existing_chunks
  avail_kb = mem_available_kb()
  size_mb = sum(os.path.getsize(p) for p in get_existing_chunks(pkl)) / 1e6
  need_kb = int(size_mb * 1024 * 4)          # 经验：峰值 ≈ 4× pkl 体积
  budget_kb = min(int(avail_kb * 0.6), max(need_kb, 1_200_000))
  if not force and avail_kb < need_kb:
    record(SKIP, "B2 模型反序列化冒烟",
           f"可用内存 {avail_kb/1024:.0f}MB < 预估需求 {need_kb/1024:.0f}MB（{size_mb:.0f}MB pkl）→ "
           "不敢冒险 OOM 打挂设备；离车/停车时再跑 --model-load --force")
    return
  cmd = [sys.executable, "-c", MODEL_LOAD_SNIPPET, str(budget_kb * 1024), pkl]
  t0 = time.time()
  try:
    r = subprocess.run(cmd, cwd=str(OPENPILOT_ROOT), capture_output=True, text=True, timeout=600)
  except subprocess.TimeoutExpired:
    record(FAIL, "B2 模型反序列化冒烟", "600s 超时（pkl 与 tinygrad pin 不匹配时常见）")
    return
  out = ((r.stdout or "") + (r.stderr or "")).strip()
  tail = "\n        ".join(out.splitlines()[-6:])
  if r.returncode == 0 and "LOADED" in out:
    record(PASS, "B2 模型反序列化冒烟", f"{out.splitlines()[-1]}（{time.time()-t0:.1f}s, 地址空间上限 {budget_kb/1024:.0f}MB）")
  elif "MemoryError" in out:
    record(SKIP, "B2 模型反序列化冒烟", f"内存护栏触发（未验证，不是失败）：{tail}")
  else:
    record(FAIL, "B2 模型反序列化冒烟", f"exit={r.returncode}（这正是 modeld 上车崩溃的位置）：\n        {tail}")


# ---------------------------------------------------------------- 阶段 C

def _proc_stat_start_epoch(pid: int) -> float | None:
  try:
    with open(f"/proc/{pid}/stat") as f:
      fields = f.read().rsplit(")", 1)[1].split()
    starttime_ticks = int(fields[19])          # field 22 overall
    btime = 0
    with open("/proc/stat") as f:
      for line in f:
        if line.startswith("btime"):
          btime = int(line.split()[1])
    return btime + starttime_ticks / os.sysconf("SC_CLK_TCK")
  except (OSError, IndexError, ValueError):
    return None


def _running() -> dict[str, list[int]]:
  found: dict[str, list[int]] = {name: [] for name in RUNTIME_PROCS}
  for entry in os.listdir("/proc"):
    if not entry.isdigit():
      continue
    try:
      with open(f"/proc/{entry}/cmdline", "rb") as f:
        cmdline = f.read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
      continue
    for name, needle in RUNTIME_PROCS.items():
      if needle in cmdline and "sim_preflight" not in cmdline:
        found[name].append(int(entry))
  return found


def check_runtime() -> None:
  procs = _running()
  missing = [n for n in ("manager", "webuid") if not procs[n]]
  if missing:
    record(FAIL, "C1 关键进程存活", f"未运行：{', '.join(missing)}")
  else:
    record(PASS, "C1 关键进程存活", "manager / webuid 在线")

  roots, forks = [], []
  for pid in procs["manager"]:
    try:
      ppid = int(open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()[1])
      parent_is_manager = ppid in procs["manager"]
      parent_cmd = open(f"/proc/{ppid}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
      parent_is_manager, parent_cmd = False, ""
    # multiprocessing.Process 是 fork 出来的，子进程会继承 manager.py 的 cmdline，
    # 之后才 setproctitle → 不能拿 cmdline 计数，否则永远误报双实例。
    (forks if (parent_is_manager or RUNTIME_PROCS["manager"] in parent_cmd) else roots).append(pid)
  if len(roots) > 1:
    record(FAIL, "C1 manager 单实例",
           f"发现 {len(roots)} 个根 manager.py（PID {roots}）→ 会重复拉起子进程/卡 UI，先清掉多余实例")
  else:
    record(PASS, "C1 manager 单实例", f"根实例 PID {roots[0] if roots else '未检出'}")
  if forks:
    record(WARN, "C1 manager fork 子进程",
           f"{len(forks)} 个 fork 子进程仍带 manager.py 的 cmdline（PID {forks}）。正常应在 1s 内 setproctitle 改名；"
           "长期不改名 = 某个托管进程还没进到 launcher 的 setproctitle（本机 2026-10-10 实测有一个 PID 18930 已挂 39min、state=S 睡眠）")

  onroad = False
  try:
    sys.path.insert(0, str(OPENPILOT_ROOT))
    from openpilot.common.params import Params
    onroad = bool(Params().get_bool("IsOnroad"))
  except Exception:
    pass
  if onroad:
    dead = [n for n in ("selfdrived", "card", "modeld_v2", "ui") if not procs[n]]
    if dead:
      record(FAIL, "C1 行车进程存活", f"onroad 但未运行：{', '.join(dead)}（selfdrived 缺席 = UI 报 sunnypilot Unavailable）")
    else:
      record(PASS, "C1 行车进程存活", "selfdrived / card / modeld_v2 / ui 全在线")
  else:
    record(SKIP, "C1 行车进程存活", "当前 offroad，行车进程本就只在 onroad 起")

  if not CRASH_DIR.is_dir():
    record(SKIP, "C2 启动后新崩溃", f"无 {CRASH_DIR}")
    return
  ref = _proc_stat_start_epoch(procs["manager"][0]) if procs["manager"] else None
  if ref is None:
    record(SKIP, "C2 启动后新崩溃", "拿不到 manager 启动时间，无法比对")
    return
  fresh = sorted(p.name for p in CRASH_DIR.glob("*.log") if p.stat().st_mtime > ref and p.name != "error.log")
  if fresh:
    record(FAIL, "C2 启动后新崩溃", f"本次 manager 启动后新增 {len(fresh)} 个崩溃：{', '.join(fresh[-6:])}")
  else:
    record(PASS, "C2 启动后新崩溃", "本次启动后无新崩溃")


# ---------------------------------------------------------------- main

def main() -> int:
  ap = argparse.ArgumentParser(description="openpilot 上车前一致性预检")
  ap.add_argument("--runtime", action="store_true", help="设备运行时链路检查（进程存活 / 新崩溃）")
  ap.add_argument("--model-load", action="store_true", help="执行真实 pkl 反序列化冒烟（吃内存）")
  ap.add_argument("--force", action="store_true", help="忽略内存护栏，强制执行 --model-load")
  ap.add_argument("--skip-params", action="store_true", help="跳过阶段 A（参数链）")
  args = ap.parse_args()

  print("=" * 72)
  print("openpilot 上车前一致性预检（sim preflight）")
  print("=" * 72)
  keys: set[str] = set()

  print("\n阶段 A：参数链（UnknownKeyName 类）")
  if args.skip_params:
    record(SKIP, "阶段 A", "--skip-params")
  elif not PARAMS_KEYS_H.is_file():
    record(FAIL, "阶段 A", f"缺少 {PARAMS_KEYS_H}")
  else:
    try:
      keys = read_params_keys()
      record(PASS, "A0 键表可解析", f"params_keys.h 共 {len(keys)} 个键")
    except Exception as e:
      record(FAIL, "A0 键表可解析", f"{type(e).__name__}: {e}")
    if keys:
      check_params_build()
      check_native_key_abi(keys)
      check_key_registration(keys)

  print("\n阶段 B：模型/推理链（modeld 反序列化类）")
  pkl = check_model_artifacts()
  if args.model_load:
    check_model_load(pkl, args.force)
  else:
    record(SKIP, "B2 模型反序列化冒烟", "未加 --model-load（默认不跑，避免抢内存）")

  if args.runtime:
    print("\n阶段 C：运行时链（进程 / 崩溃）")
    check_runtime()

  counts = {lvl: sum(1 for r in _RESULTS if r[0] == lvl) for lvl in (PASS, WARN, FAIL, SKIP)}
  print("\n" + "=" * 72)
  print(f"结果：{counts[PASS]} 通过 / {counts[WARN]} 警告 / {counts[SKIP]} 跳过 / {counts[FAIL]} 失败")
  if counts[FAIL]:
    print("失败项：")
    for lvl, name, detail in _RESULTS:
      if lvl == FAIL:
        print(f"  ❌ {name}")
        if detail:
          print(f"     {detail.splitlines()[0]}")
    print("=" * 72)
    return 1
  print("🎉 预检通过（WARN/SKIP 已逐条列出，未静默忽略）")
  print("=" * 72)
  return 0


if __name__ == "__main__":
  sys.exit(main())
