"""EPS 8965B4512000 SecOC patch tools for op 助手.

Wraps two vendored repositories:

- ``eps-telescope`` (ai/vendor/eps_telescope): read-only layered probe used to
  determine whether the vehicle is eligible for the patch procedure.
- ``8965B4512000-FW-PATCH`` (ai/vendor/eps_patch): the reviewed flash writer for
  EPS part number ``8965B4512000``.

Chat-callable tools are limited to read-only or preparatory operations. The
destructive ``patch`` and ``restore`` writers can be executed through the panel
under strict confirmation and pty-based YES automation, or manually in a
foreground interactive SSH TTY.
"""

from __future__ import annotations

import hashlib
import json
import os
import pty
import select
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


EPS_PATCH_SCRIPT = Path(__file__).resolve().parents[3] / "vendor" / "eps_patch" / "eps_patch.py"
EPS_TELESCOPE_SCRIPT = Path(__file__).resolve().parents[3] / "vendor" / "eps_telescope" / "probe.py"
ARTIFACT_ROOT = Path("/data/eps-patch/artifacts")
TELESCOPE_ARTIFACT_ROOT = Path("/data/eps-telescope/artifacts")


def _patch_script() -> Path:
  if not EPS_PATCH_SCRIPT.exists():
    return Path("/data/eps-patch/app/eps_patch.py")
  return EPS_PATCH_SCRIPT


def _telescope_script() -> Path:
  if not EPS_TELESCOPE_SCRIPT.exists():
    return Path("/data/eps-telescope/app/probe.py")
  return EPS_TELESCOPE_SCRIPT


def _python() -> str:
  """Prefer the same interpreter as the current process; fall back to python3.12."""
  exe = sys.executable
  if exe and Path(exe).name.lower().startswith("python"):
    return exe
  return "python3.12"


def _run_patch(*args: str, timeout: int = 600) -> dict[str, Any]:
  """Run one eps_patch.py subcommand and capture its output."""
  cmd = [_python(), str(_patch_script()), *args]
  try:
    result = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      timeout=timeout,
      cwd=str(_patch_script().parent),
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


def _run_telescope(*args: str, timeout: int = 900) -> dict[str, Any]:
  """Run eps-telescope probe.py and capture its output."""
  cmd = [_python(), str(_telescope_script()), *args]
  try:
    result = subprocess.run(
      cmd,
      capture_output=True,
      text=True,
      timeout=timeout,
      cwd=str(_telescope_script().parent),
    )
  except FileNotFoundError as exc:
    return {"ok": False, "error": f"{_python()} not found: {exc}"}
  except subprocess.TimeoutExpired as exc:
    return {"ok": False, "error": f"eps-telescope command timed out after {timeout}s", "stdout": exc.stdout or "", "stderr": exc.stderr or ""}
  return {
    "ok": result.returncode == 0,
    "returncode": result.returncode,
    "stdout": result.stdout,
    "stderr": result.stderr,
    "command": " ".join(cmd),
  }


def _artifact_root() -> Path:
  return ARTIFACT_ROOT


def _telescope_artifact_root() -> Path:
  return TELESCOPE_ARTIFACT_ROOT


def list_pandas() -> dict[str, Any]:
  """Enumerate available comma pandas and label internal vs external USB.

  Returns a dict with a recommended serial (internal first, then first external
  USB). External USB devices are labelled by enumeration order.
  """
  try:
    from panda import Panda
  except Exception as exc:
    return {"ok": False, "error": f"panda library unavailable: {exc}", "pandas": []}

  try:
    serials = Panda.list()
  except Exception as exc:
    return {"ok": False, "error": f"Panda.list() failed: {exc}", "pandas": []}

  items: list[dict[str, Any]] = []
  external_usb_index = 0
  recommended: str | None = None
  for serial in serials:
    try:
      with Panda(serial, claim=False) as panda:
        is_internal = bool(panda.is_internal())
        is_usb = bool(panda.is_connected_usb())
    except Exception:
      is_internal = False
      is_usb = False

    if is_internal:
      label = "内置 Panda"
      kind = "internal"
      if recommended is None:
        recommended = serial
    elif is_usb:
      external_usb_index += 1
      label = f"外接 USB #{external_usb_index}"
      kind = "usb"
      if recommended is None:
        recommended = serial
    else:
      label = "其他连接"
      kind = "other"

    items.append({
      "serial": serial,
      "kind": kind,
      "label": label,
      "is_internal": is_internal,
      "is_usb": is_usb,
    })

  return {
    "ok": True,
    "pandas": items,
    "recommended": recommended,
    "count": len(items),
  }


def _state_path() -> Path:
  return _artifact_root() / "state.json"


def _probe_report_path() -> Path:
  return _artifact_root() / "probe" / "faci-pe-cycle-report.json"


def _latest_telescope_report(root: Path | None = None) -> Path | None:
  root = root or _telescope_artifact_root()
  if not root.exists():
    return None
  candidates = sorted(root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
  for c in candidates:
    report = c / "report.json"
    if report.exists():
      return report
  return None


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
      action=tool,
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


def _parse_telescope_report(path: Path | None = None) -> dict[str, Any]:
  if path is None:
    path = _latest_telescope_report()
  if not path:
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
    "telescope_report": _parse_telescope_report(),
  }
  return payload


def _derive_eps_state(
  state: dict[str, Any] | None,
  report: dict[str, Any] | None,
  tel_report: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
  """Derive a high-level EPS workflow state and a detail payload.

  States:
    unknown          - no telescope report, no patch state
    not_compatible   - telescope says this vehicle is not eligible
    ready_to_probe   - telescope passed (verified_variant), no probe yet
    already_patched  - telescope says already patched, or patch state PASS
    probe_pass       - probe completed, ready for writer
    patch_in_progress- patch state machine is in the middle
    failed           - terminal FAILED or RECOVERY_REQUIRED
  """
  classification = tel_report.get("classification", {}).get("classification") if tel_report else None
  stage = state.get("stage") if state else None
  probe_present = bool(report)
  probe_pass = report.get("outcome") == "PASS" if report else False

  if stage == "PASS" or classification == "already_patched":
    return "already_patched", {
      "stage": stage,
      "classification": classification,
      "probe_pass": probe_pass,
      "message": "EPS 已经是 patch 完成状态，无需再次刷写。",
    }

  if not tel_report:
    return "unknown", {
      "stage": stage,
      "classification": classification,
      "probe_pass": probe_pass,
      "message": "尚未进行 eps-telescope 探测。",
      "next_step": "eps_telescope_probe",
    }

  if classification not in ("verified_variant", "already_patched"):
    return "not_compatible", {
      "stage": stage,
      "classification": classification,
      "probe_pass": probe_pass,
      "message": "当前车辆/固件变体不符合 8965B4512000 patch 条件。",
      "next_step": "eps_telescope_classify",
    }

  if state and stage in ("FAILED", "RECOVERY_REQUIRED"):
    return "failed", {
      "stage": stage,
      "classification": classification,
      "probe_pass": probe_pass,
      "message": "上一次 patch/restore 进入失败或需要恢复的状态。",
      "next_step": "eps_patch_diagnose / eps_patch_prepare_restore",
    }

  if state and stage not in (None, "PASS"):
    return "patch_in_progress", {
      "stage": stage,
      "classification": classification,
      "probe_pass": probe_pass,
      "message": "patch 流程已部分执行，需要继续或恢复。",
      "next_step": "continue_patch",
    }

  if probe_pass:
    return "probe_pass", {
      "stage": stage,
      "classification": classification,
      "probe_pass": probe_pass,
      "message": "Probe 通过，可以进入 patch writer。",
      "next_step": "eps_patch_prepare_patch",
    }

  return "ready_to_probe", {
    "stage": stage,
    "classification": classification,
    "probe_pass": probe_pass,
    "message": "telescope 判定通过，可以运行 eps_patch_probe。",
    "next_step": "eps_patch_probe",
  }


def eps_patch_status() -> dict[str, Any]:
  """Read current EPS patch workflow state and probe evidence (read-only)."""
  root = _artifact_root()
  probe_dir = root / "probe"
  failures_dir = root / "failures"
  state = _parse_state()
  report = _parse_probe_report()
  tel_report = _parse_telescope_report()

  probe_present = probe_dir.exists() and (probe_dir / "faci-pe-cycle-report.json").exists()
  probe_pass = report.get("outcome") == "PASS" if report else False
  classification = tel_report.get("classification", {}).get("classification") if tel_report else None

  high_state, state_detail = _derive_eps_state(state, report, tel_report)

  next_command = None
  stage = state.get("stage") if state else None
  if high_state == "unknown":
    next_command = "eps_telescope_probe"
  elif high_state == "not_compatible":
    next_command = "eps_telescope_classify   # 确认是否可刷"
  elif high_state == "ready_to_probe":
    next_command = "eps_patch_probe"
  elif high_state == "probe_pass":
    next_command = "python3.12 eps_patch.py patch   # 可一键或前台 TTY 执行"
  elif high_state == "patch_in_progress":
    next_command = "python3.12 eps_patch.py patch   # 继续同一命令"
  elif high_state in ("failed",):
    next_command = "python3.12 eps_patch.py restore   # 或一键恢复"

  return _attach_ui_card({
    "ok": True,
    "state_name": high_state,
    "state_detail": state_detail,
    "stage": stage,
    "probe_present": probe_present,
    "probe_pass": probe_pass,
    "telescope_classification": classification,
    "artifact_root": str(root),
    "telescope_artifact_root": str(_telescope_artifact_root()),
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
      "chat 可调用 eps_telescope_probe（只读判定）、eps_patch_probe（只读建证）、"
      "status（读状态）、prepare（检查下一步）。"
      "patch/restore writer 可通过面板一键执行（带多重确认），也可在前台交互 SSH TTY 手动执行。"
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

  tel = _parse_telescope_report()
  classification = tel.get("classification", {}).get("classification") if tel else None
  if classification not in ("verified_variant", "already_patched"):
    return _attach_ui_card({
      "ok": False,
      "error": "eps-telescope 尚未判定为 verified_variant / already_patched，不能进入 eps_patch_probe。",
      "classification": classification,
      "next_step": "eps_telescope_probe",
    })

  args = ["probe"]
  if serial:
    args += ["--serial", serial]
  result = _run_patch(*args, timeout=900)
  result["stage_after"] = _parse_state().get("stage")
  result["probe_pass"] = _parse_probe_report().get("outcome") == "PASS"
  return _attach_ui_card(_audit("eps_patch_probe", result))


def _backup_info() -> dict[str, Any]:
  """Summarize the original sector backups created by a successful probe."""
  probe_dir = _artifact_root() / "probe"
  target = probe_dir / "original-sector-0x88000.bin"
  crc = probe_dir / "original-sector-0xf8000.bin"
  meta = probe_dir / "recovery-metadata.json"
  info: dict[str, Any] = {"available": False}
  for name, path in [("target", target), ("crc", crc), ("metadata", meta)]:
    if path.exists():
      try:
        info[name] = {
          "path": str(path),
          "size": path.stat().st_size,
          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
      except Exception as exc:
        info[name] = {"path": str(path), "error": str(exc)}
  info["available"] = bool(info.get("target") and info.get("crc"))
  return info


def eps_patch_prepare_patch(
  *,
  get_state_reader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
  """Check prerequisites and emit the patch command / options for the operator."""
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

  return _attach_ui_card(_audit("eps_patch_prepare_patch", {
    "ok": True,
    "stage": stage,
    "message": "已满足 patch 前置条件。",
    "manual_command": "python3.12 eps_patch.py patch",
    "one_click_available": True,
    "one_click_command": "python3.12 eps_patch.py patch",
    "backup_info": _backup_info(),
    "manual_steps": [
      "1. 确保车辆静止、台架稳定供电。",
      "2. 点击“一键刷写”或在 /data/eps-patch/app 执行 python3.12 eps_patch.py patch",
      "3. 核对终端/面板显示的 WRITE-TARGET / WRITE-CRC 交易块。",
      "4. 确认无误后授权（面板已自动处理 YES）。",
      "5. 命令保存 checkpoint 并退出后，完全断电（车辆/EPS/comma）。",
      "6. 等待放电后恢复供电，重新打开面板点击“继续刷写”。",
    ],
    "warning": "patch 会擦写 EPS Flash，失败可能导致 EPS 不可用；请备好外部编程器或专业恢复方案。",
  }))


def eps_patch_prepare_restore(
  *,
  get_state_reader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
  """Check prerequisites and emit the restore command / options for the operator."""
  err = _offroad_guard(get_state_reader)
  if err:
    return err

  state = _parse_state()
  stage = state.get("stage")
  recoverable = bool(state) or _backup_info()["available"]

  if not recoverable:
    return _attach_ui_card({
      "ok": False,
      "error": "没有可恢复的 incident/state 或 probe 备份。如 Flash 状态未知，请使用外部编程器。",
    })

  return _attach_ui_card(_audit("eps_patch_prepare_restore", {
    "ok": True,
    "stage": stage,
    "message": "可以进入 restore。",
    "manual_command": "python3.12 eps_patch.py restore",
    "one_click_available": True,
    "one_click_command": "python3.12 eps_patch.py restore",
    "backup_info": _backup_info(),
    "manual_steps": [
      "1. 确保车辆静止、台架稳定供电。",
      "2. 点击“一键恢复”或在 /data/eps-patch/app 执行 python3.12 eps_patch.py restore",
      "3. 核对面板显示的 RESTORE-SECTOR 交易块。",
      "4. 确认无误后授权（面板已自动处理 YES）。",
      "5. 命令保存 checkpoint 并退出后，完全断电（车辆/EPS/comma）。",
      "6. 等待放电后恢复供电，重新打开面板点击“继续恢复”。",
    ],
    "warning": "restore 会擦写 EPS Flash；失败可能导致 EPS 不可用。",
  }))


def _writer_prerequisites_ok(command: str, get_state_reader: Callable[..., Any] | None) -> dict[str, Any] | None:
  """Shared gate for one-click patch/restore writer."""
  err = _offroad_guard(get_state_reader)
  if err:
    return err

  allowed, reason = _is_shell_allowed()
  if not allowed:
    return {"ok": False, "error": reason}

  state = _parse_state()
  stage = state.get("stage") if state else None
  report = _parse_probe_report()

  if command == "patch":
    if not report or report.get("outcome") != "PASS":
      return {"ok": False, "error": "尚未完成可信 probe，无法一键 patch。请先运行 eps_patch_probe。"}
    if stage == "PASS":
      return {"ok": False, "error": "当前已经是 PASS 状态，无需再次 patch。"}
  elif command == "restore":
    if not state and not _backup_info()["available"]:
      return {"ok": False, "error": "没有可恢复的 incident/state 或 probe 备份。"}
  else:
    return {"ok": False, "error": f"未知 writer 命令: {command}"}

  return None


def _is_shell_allowed() -> tuple[bool, str]:
  """Check if shell actions are allowed in current mode (matches routes.py)."""
  try:
    from ai.server.deps import get_state_reader as _gsr
    from ai.system.admin import is_admin_mode as _iam
    from ai.system.safety import is_action_allowed
    reader = _gsr()
    if reader is None:
      return False, "vehicle state reader unavailable"
    state = reader.update(timeout=0)
    from ai.server.deps import params as _params
    return is_action_allowed("shell", state, admin=_iam(_params()))
  except Exception as exc:
    return False, f"shell permission check failed: {exc}"


class WriterRunner:
  """Run eps_patch.py patch/restore inside a pty and auto-type YES.

  The original eps_patch.py requires an interactive TTY and a human typed YES.
  This class allocates a pseudo-terminal, streams stdout/stderr to a callback,
  and sends YES when the prompt appears. It is intentionally separate from the
  HTTP layer so it can be reused by chat tools or other callers.
  """

  YES_PROMPT_EN = b"Type YES to continue:"
  YES_PROMPT_CN = "\u8f93\u5165\u5927\u5199 YES \u7ee7\u7eed".encode("utf-8")

  def __init__(
    self,
    command: str,
    *,
    serial: str = "",
    on_line: Callable[[str], object] | None = None,
    on_prompt: Callable[[], object] | None = None,
  ):
    if command not in ("patch", "restore"):
      raise ValueError(f"unsupported writer command: {command}")
    self.command = command
    self.serial = serial or ""
    self.on_line = on_line
    self.on_prompt = on_prompt
    self.proc: subprocess.Popen[str] | None = None
    self.returncode: int | None = None
    self.power_cycle_seen = False
    self.yes_sent = False
    self.lines: list[dict[str, str]] = []

  def _build_cmd(self) -> list[str]:
    cmd = [_python(), str(_patch_script()), self.command]
    if self.serial:
      cmd += ["--serial", self.serial]
    return cmd

  def _emit_line(self, line: str) -> None:
    self.lines.append({"t": f"{time.monotonic():.3f}", "line": line})
    if self.on_line:
      try:
        self.on_line(line)
      except Exception:
        pass

  def run(self) -> dict[str, Any]:
    """Run the writer synchronously. Caller should run in a thread/executor."""
    master_fd, slave_fd = pty.openpty()
    try:
      self.proc = subprocess.Popen(
        self._build_cmd(),
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        text=False,
        close_fds=True,
        cwd=str(_patch_script().parent),
      )
    except Exception as exc:
      os.close(master_fd)
      os.close(slave_fd)
      return {"ok": False, "error": f"failed to start writer: {exc}"}
    finally:
      try:
        os.close(slave_fd)
      except OSError:
        pass

    try:
      buffer = b""
      while True:
        ready, _, _ = select.select([master_fd], [], [], 0.2)
        if ready:
          try:
            chunk = os.read(master_fd, 4096)
          except OSError:
            chunk = b""
          if not chunk:
            break
          buffer += chunk
          while b"\n" in buffer:
            line, _, buffer = buffer.partition(b"\n")
            text = line.decode("utf-8", errors="replace").rstrip("\r")
            self._emit_line(text)
            if "Checkpoint saved" in text or "断电重启" in text:
              self.power_cycle_seen = True
            if (
              not self.yes_sent
              and (self.YES_PROMPT_EN in line or self.YES_PROMPT_CN in line)
            ):
              self.yes_sent = True
              if self.on_prompt:
                try:
                  self.on_prompt()
                except Exception:
                  pass
              try:
                os.write(master_fd, b"YES\n")
              except OSError as exc:
                self._emit_line(f"[runner] failed to send YES: {exc}")
        elif self.proc.poll() is not None:
          break

      try:
        self.returncode = self.proc.wait(timeout=30)
      except subprocess.TimeoutExpired:
        self.proc.kill()
        self.returncode = self.proc.wait()

      # Drain remaining output.
      while True:
        ready, _, _ = select.select([master_fd], [], [], 0.3)
        if not ready:
          break
        try:
          chunk = os.read(master_fd, 4096)
        except OSError:
          chunk = b""
        if not chunk:
          break
        buffer += chunk
      if buffer:
        text = buffer.decode("utf-8", errors="replace").rstrip("\r\n")
        for line in text.splitlines():
          self._emit_line(line)

      result = {
        "ok": self.returncode == 0,
        "returncode": self.returncode,
        "command": " ".join(self._build_cmd()),
        "power_cycle_seen": self.power_cycle_seen,
        "yes_sent": self.yes_sent,
        "stage_after": _parse_state().get("stage"),
      }
      if not result["ok"]:
        result["error"] = self.lines[-1]["line"] if self.lines else "writer failed"
      return result
    finally:
      try:
        os.close(master_fd)
      except OSError:
        pass
      if self.proc is not None and self.proc.poll() is None:
        try:
          self.proc.kill()
        except Exception:
          pass


def eps_patch_run_writer(
  *,
  command: str,
  serial: str = "",
  confirm: bool = False,
  i_understand: str = "",
  get_state_reader: Callable[..., Any] | None = None,
  on_line: Callable[[str], object] | None = None,
) -> dict[str, Any]:
  """Run patch/restore writer with pty-based YES automation.

  Requires confirm=true AND i_understand="brick_risk".
  """
  if not confirm:
    return {
      "ok": True,
      "needs_confirmation": True,
      "hint": "将执行 EPS Flash writer，可能导致 EPS 变砖。设置 confirm=true 并在二次确认中勾选了解风险后继续。",
    }
  if i_understand != "brick_risk":
    return {"ok": False, "error": "缺少二次确认：请在面板勾选“我已了解变砖风险”后再执行。"}

  prereq = _writer_prerequisites_ok(command, get_state_reader)
  if prereq:
    return prereq

  runner = WriterRunner(command, serial=serial, on_line=on_line)
  result = runner.run()
  result["command"] = " ".join(runner._build_cmd())
  result["backup_info"] = _backup_info()
  return _attach_ui_card(_audit(f"eps_patch_run_writer:{command}", result))


def eps_patch_diagnose() -> dict[str, Any]:
  """Summarize the latest failure or indeterminate incident for chat review."""
  failures_dir = _artifact_root() / "failures"
  latest = failures_dir / "last-probe-failure.json"
  state = _parse_state()
  outcome = state.get("outcome") or state.get("stage")
  tel_report = _parse_telescope_report()

  diag: dict[str, Any] = {
    "ok": True,
    "artifact_root": str(_artifact_root()),
    "state": state,
    "telescope_classification": tel_report.get("classification", {}).get("classification") if tel_report else None,
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

  return _attach_ui_card(_audit("eps_patch_diagnose", diag))


# --- eps-telescope integration ------------------------------------------------


def _telescope_ui_card(payload: dict[str, Any]) -> dict[str, Any]:
  payload["ui_card"] = {
    "type": "eps_telescope",
    "report": _parse_telescope_report(),
  }
  return payload


def eps_telescope_status(
  *,
  artifacts_dir: str = "",
) -> dict[str, Any]:
  """Read the latest eps-telescope report (read-only)."""
  root = Path(artifacts_dir) if artifacts_dir else _telescope_artifact_root()
  report_path = _latest_telescope_report(root)
  report = _parse_telescope_report(report_path)
  classification = report.get("classification", {}).get("classification") if report else None

  return _telescope_ui_card({
    "ok": True,
    "artifact_root": str(root),
    "latest_report": str(report_path) if report_path else None,
    "classification": classification,
    "guidance": report.get("guidance", []),
    "summary": report.get("meta") if report else None,
  })


def eps_telescope_classify(
  *,
  artifacts_dir: str = "",
) -> dict[str, Any]:
  """Return the telescope classification decision and next-step guidance."""
  root = Path(artifacts_dir) if artifacts_dir else _telescope_artifact_root()
  report_path = _latest_telescope_report(root)
  report = _parse_telescope_report(report_path)
  classification = report.get("classification", {}).get("classification") if report else None

  if not report:
    return _telescope_ui_card({
      "ok": False,
      "error": "尚未找到 eps-telescope report。请先运行 eps_telescope_probe。",
      "next_step": "eps_telescope_probe",
    })

  next_step = None
  if classification in ("verified_variant", "already_patched"):
    next_step = "eps_patch_probe"
  elif classification == "sa_blocked":
    next_step = "采集 seed/key 对进行 SecurityAccess 逆向（不可直接进入 patch）"
  elif classification == "envelope_blocked":
    next_step = "提取该变体 PayloadBuildSecret（不可直接进入 patch）"
  elif classification in ("egg_variant", "egg_variant_relocated", "no_egg"):
    next_step = "离线对照指纹或重新定位 patch 点（不可直接进入 patch）"
  else:
    next_step = "重新运行 eps_telescope_probe 或降级为 --depth uds 采集更多信息"

  return _telescope_ui_card(_audit("eps_telescope_classify", {
    "ok": True,
    "classification": classification,
    "guidance": report.get("guidance", []),
    "next_step": next_step,
    "safe_to_patch": classification in ("verified_variant", "already_patched"),
    "report_path": str(report_path),
  }))


def eps_telescope_probe(
  *,
  serial: str = "",
  addr: str = "",
  depth: str = "shellcode",
  no_egg_scan: bool = False,
  no_fingerprint: bool = False,
  artifacts_dir: str = "",
  confirm: bool = False,
  get_state_reader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
  """Run the read-only eps-telescope layered probe (stops manager/pandad)."""
  if depth not in ("uds", "sa", "shellcode"):
    return {"ok": False, "error": f"depth 必须是 uds/sa/shellcode 之一，收到 {depth}"}

  if not confirm:
    return _telescope_ui_card({
      "ok": True,
      "needs_confirmation": True,
      "hint": "将停止 manager/pandad，对 EPS 执行只读分层探测（eps-telescope）。设置 confirm=true 执行。",
    })

  err = _offroad_guard(get_state_reader)
  if err:
    return err

  out_dir = str(Path(artifacts_dir) if artifacts_dir else _telescope_artifact_root())
  args = ["--depth", depth, "--artifacts-dir", out_dir]
  if serial:
    args += ["--serial", serial]
  if addr:
    args += ["--addr", addr]
  if no_egg_scan:
    args += ["--no-egg-scan"]
  if no_fingerprint:
    args += ["--no-fingerprint"]

  result = _run_telescope(*args, timeout=1200)
  result["classification_after"] = _parse_telescope_report().get("classification", {}).get("classification")
  return _telescope_ui_card(_audit("eps_telescope_probe", result))
