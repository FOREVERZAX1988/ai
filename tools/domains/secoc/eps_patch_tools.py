"""EPS 8965B4512000 SecOC patch tools for op 助手.

Wraps the vendored ``8965B4512000-FW-PATCH`` workflow. Chat-callable tools are
limited to read-only or preparatory operations; the destructive ``patch`` and
``restore`` writers still require a foreground interactive SSH TTY and a human
typed ``YES``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any


EPS_PATCH_SCRIPT = Path(__file__).resolve().parents[3] / "vendor" / "eps_patch" / "eps_patch.py"
ARTIFACT_ROOT = Path("/data/eps-patch/artifacts")


def _script() -> Path:
  if not EPS_PATCH_SCRIPT.exists():
    return Path("/data/eps-patch/app/eps_patch.py")
  return EPS_PATCH_SCRIPT


def _python() -> str:
  """Prefer the same interpreter as the current process; fall back to python3.12."""
  exe = sys.executable
  if exe and Path(exe).name.lower().startswith("python"):
    return exe
  return "python3.12"


def _run(*args: str, timeout: int = 600) -> dict[str, Any]:
  """Run one eps_patch.py subcommand and capture its output."""
  cmd = [_python(), str(_script()), *args]
  try:
    result = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      timeout=timeout,
      cwd=str(_script().parent),
    )
  except FileNotFoundError as exc:
    return {"ok": False, "error": f"{_python()} not found: {exc}"}
  except subprocess.TimeoutExpired as exc:
    return {"ok": False, "error": f"eps_patch command timed out after {timeout}s", "stdout": exc.stdout or "", "stderr": exc.stderr or ""}
  return {
    "ok": result.returncode == 0,
    "returncode": result.returncode,
    "stdout": result.stdout,
    "stderr": result.stderr,
    "command": " ".join(cmd),
  }


def _artifact_root() -> Path:
  return ARTIFACT_ROOT


def _state_path() -> Path:
  return _artifact_root() / "state.json"


def _probe_report_path() -> Path:
  return _artifact_root() / "probe" / "faci-pe-cycle-report.json"


def _offroad_guard(get_state_reader: Callable[..., Any] | None) -> dict[str, Any] | None:
  if get_state_reader is None:
    return None
  try:
    state = get_state_reader().update(timeout=0)
    if getattr(state, "started", False) and not getattr(state, "force_offroad", False):
      return {"ok": False, "error": "EPS 刷写相关操作仅能在 offroad 下进行。"}
  except Exception:
    pass
  return None


def _audit(tool: str, result: dict[str, Any]) -> dict[str, Any]:
  try:
    from ai.tools.domains.platform.audit_store import record_audit
    record_audit(
      action=f"eps_patch_{tool}",
      tool=tool,
      detail={
        "ok": result.get("ok"),
        "command": result.get("command"),
        "error": result.get("error"),
        "stage": result.get("stage"),
      },
      ok=bool(result.get("ok")),
    )
  except Exception:
    pass
  return result


def _parse_state() -> dict[str, Any]:
  path = _state_path()
  if not path.exists():
    return {}
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception as exc:
    return {"_parse_error": str(exc)}


def _parse_probe_report() -> dict[str, Any]:
  path = _probe_report_path()
  if not path.exists():
    return {}
  try:
    return json.loads(path.read_text(encoding="utf-8"))
  except Exception as exc:
    return {"_parse_error": str(exc)}


def _attach_ui_card(payload: dict[str, Any]) -> dict[str, Any]:
  payload["ui_card"] = {
    "type": "eps_patch",
    "state": _parse_state(),
    "probe_report": _parse_probe_report(),
  }
  return payload


def eps_patch_status() -> dict[str, Any]:
  """Read current EPS patch workflow state and probe evidence (read-only)."""
  root = _artifact_root()
  probe_dir = root / "probe"
  failures_dir = root / "failures"
  state = _parse_state()
  report = _parse_probe_report()

  probe_present = probe_dir.exists() and (probe_dir / "faci-pe-cycle-report.json").exists()
  probe_pass = report.get("outcome") == "PASS" if report else False

  next_command = None
  stage = state.get("stage") if state else None
  if not probe_present:
    next_command = "eps_patch_probe"
  elif stage in ("PROBED", "TARGET_PRECHECKED", "TARGET_COMMITTED", "CRC_PRECHECKED", "CRC_COMMITTED"):
    next_command = "python3.12 eps_patch.py patch   # 前台 TTY 手动执行"
  elif stage and "RESTORE" in str(stage).upper():
    next_command = "python3.12 eps_patch.py restore   # 前台 TTY 手动执行"

  return _attach_ui_card({
    "ok": True,
    "stage": stage,
    "probe_present": probe_present,
    "probe_pass": probe_pass,
    "artifact_root": str(root),
    "state": state,
    "probe_report_summary": {
      "outcome": report.get("outcome"),
      "ecu_identity": report.get("ecu_identity"),
      "application_f181": report.get("application_f181"),
      "boot_f181": report.get("boot_f181"),
      "panda_serial": report.get("panda_serial"),
    } if report else None,
    "next_command": next_command,
    "ai_rule": (
      "EPS 8965B4512000 刷写仅支持静止台架。"
      "chat 可调用 probe（只读建证）、status（读状态）、prepare（检查下一步）。"
      "真正的 patch/restore writer 必须在前台交互 SSH TTY 手动执行，并输入大写 YES；"
      "每次 writer 后需要完整断电重启 comma/EPS。"
    ),
  })


def eps_patch_probe(
  *,
  serial: str = "",
  confirm: bool = False,
  get_state_reader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
  """Run the read-only EPS probe workflow (stops manager/pandad)."""
  if not confirm:
    return _attach_ui_card({
      "ok": True,
      "needs_confirmation": True,
      "hint": "将停止 manager/pandad，对 EPS 8965B4512000 执行只读 probe。设置 confirm=true 执行。",
    })

  err = _offroad_guard(get_state_reader)
  if err:
    return err

  args = ["probe"]
  if serial:
    args += ["--serial", serial]
  result = _run(*args, timeout=900)
  result["stage_after"] = _parse_state().get("stage")
  result["probe_pass"] = _parse_probe_report().get("outcome") == "PASS"
  return _attach_ui_card(_audit("probe", result))


def eps_patch_prepare_patch(
  *,
  get_state_reader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
  """Check prerequisites and emit the manual patch command for the operator."""
  err = _offroad_guard(get_state_reader)
  if err:
    return err

  state = _parse_state()
  stage = state.get("stage")
  report = _parse_probe_report()
  if not report or report.get("outcome") != "PASS":
    return _attach_ui_card({
      "ok": False,
      "error": "尚未完成可信 probe，无法进入 patch。请先运行 eps_patch_probe。",
      "next_step": "eps_patch_probe",
    })

  if stage in ("PASS",):
    return _attach_ui_card({
      "ok": True,
      "message": "当前已经是 PASS 状态，无需继续 patch。",
      "stage": stage,
    })

  return _attach_ui_card(_audit("prepare_patch", {
    "ok": True,
    "stage": stage,
    "message": "已满足 patch 前置条件。",
    "manual_command": "python3.12 eps_patch.py patch",
    "manual_steps": [
      "1. 确保车辆静止、台架稳定供电、SSH 为前台交互 TTY。",
      "2. 在 /data/eps-patch/app 目录执行: python3.12 eps_patch.py patch",
      "3. 核对终端显示的 WRITE-TARGET / WRITE-CRC 交易块。",
      "4. 完全一致后输入大写 YES 授权。",
      "5. 命令保存 checkpoint 并退出后，完全断电（车辆/EPS/comma）。",
      "6. 等待放电后恢复供电，重新 SSH，重复执行同一条命令，直到 PASS。",
    ],
    "warning": "patch 会擦写 EPS Flash，失败可能导致 EPS 不可用；请备好外部编程器或专业恢复方案。",
  }))


def eps_patch_prepare_restore(
  *,
  get_state_reader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
  """Check prerequisites and emit the manual restore command for the operator."""
  err = _offroad_guard(get_state_reader)
  if err:
    return err

  state = _parse_state()
  stage = state.get("stage")
  recoverable = bool(state)

  if not recoverable:
    return _attach_ui_card({
      "ok": False,
      "error": "没有可恢复的 incident/state。如 Flash 状态未知，请使用外部编程器。",
    })

  return _attach_ui_card(_audit("prepare_restore", {
    "ok": True,
    "stage": stage,
    "message": "已发现持久化 incident，可以进入 restore。",
    "manual_command": "python3.12 eps_patch.py restore",
    "manual_steps": [
      "1. 确保车辆静止、台架稳定供电、SSH 为前台交互 TTY。",
      "2. 在 /data/eps-patch/app 目录执行: python3.12 eps_patch.py restore",
      "3. 核对终端显示的 RESTORE-SECTOR 交易块。",
      "4. 完全一致后输入大写 YES 授权。",
      "5. 命令保存 checkpoint 并退出后，完全断电（车辆/EPS/comma）。",
      "6. 等待放电后恢复供电，重新 SSH，重复执行同一条命令，直到 PASS。",
    ],
    "warning": "restore 会擦写 EPS Flash；失败可能导致 EPS 不可用。",
  }))


def eps_patch_diagnose() -> dict[str, Any]:
  """Summarize the latest failure or indeterminate incident for chat review."""
  failures_dir = _artifact_root() / "failures"
  latest = failures_dir / "last-probe-failure.json"
  state = _parse_state()
  outcome = state.get("outcome") or state.get("stage")

  diag: dict[str, Any] = {
    "ok": True,
    "artifact_root": str(_artifact_root()),
    "state": state,
  }

  if latest.exists():
    try:
      failure = json.loads(latest.read_text(encoding="utf-8"))
      diag["last_probe_failure"] = {
        "outcome": failure.get("outcome"),
        "identity": failure.get("identity"),
        "magic": failure.get("magic"),
        "faci_snapshots": failure.get("faci_snapshots"),
        "sector_summary": failure.get("sector_summary"),
      }
    except Exception as exc:
      diag["last_probe_failure_error"] = str(exc)

  if outcome in ("TARGET_INDETERMINATE", "CRC_INDETERMINATE", "RECOVERY_REQUIRED"):
    diag["recommendation"] = "不要再运行 patch。保留 artifacts 后按 prepare_restore 指引执行 restore，或寻求外部编程器。"
  elif outcome == "PASS":
    diag["recommendation"] = "Flash 级 PASS。请在静止台架上继续验证 RX SecOC 行为，不要直接道路测试。"
  else:
    diag["recommendation"] = "请检查 status 中的 stage 和 probe_report，按对应 prepare 指引操作。"

  return _attach_ui_card(_audit("diagnose", diag))
