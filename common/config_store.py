"""Persistent storage for ai_* settings — no params_keys.h / compile required."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from ai.common.op_params import import_openpilot_params
from ai.common.params import ITEMS
from ai.system.paths import is_comma_device, openpilot_root

# 2026-08-27: 大字段拆独立文件——config.json 全量写 5MB（web_sessions/rag_documents）
# 造成写放大风暴（29 分钟写 6.4GB），系统 IO 拥塞 → restore/put 卡死、aid 无响应。
# 大字段独立文件只在值变化时写；主 config.json 只写小字段（~200KB）。
_LARGE_KEYS = frozenset({"ai_web_sessions", "ai_rag_documents"})
_MIN_SAVE_INTERVAL = 1.0  # 最小写盘间隔（秒），防写放大风暴

_EXTRA_DEFAULTS: dict[str, dict[str, str]] = {
  "ai_usage_log": {"param_type": "STRING", "default": ""},
  "ai_embedding_usage_log": {"param_type": "STRING", "default": ""},
  "ai_param_watchlist": {"param_type": "STRING", "default": ""},
  "ai_param_watchlist_baseline": {"param_type": "STRING", "default": ""},
  "ai_stream": {"param_type": "STRING", "default": "1"},
}

_LEGACY_GITHUB_PAT_PARAM = "GithubActionsPat"
_AI_GITHUB_PAT_KEY = "ai_github_actions_pat"

_store: "AiConfigStore | None" = None
_store_lock = threading.Lock()


def ai_config_path() -> Path:
  env = (os.environ.get("AI_CONFIG_PATH") or "").strip()
  if env:
    return Path(env).expanduser().resolve()
  if is_comma_device():
    return Path("/data/ai/config.json")
  home = Path.home() / ".comma" / "ai" / "config.json"
  if home.parent.exists() or not (openpilot_root() / "ai").is_dir():
    return home
  return openpilot_root() / "ai" / "data" / "user" / "config.json"


def _build_schema() -> dict[str, dict[str, str]]:
  schema: dict[str, dict[str, str]] = {}
  for item in ITEMS:
    key = item.get("key", "")
    if key.startswith("ai_"):
      schema[key] = {
        "param_type": item.get("param_type", "STRING"),
        "default": item.get("default", ""),
      }
  for key, meta in _EXTRA_DEFAULTS.items():
    schema.setdefault(key, meta)
  return schema


def is_ai_param(key: str) -> bool:
  return bool(key) and key.startswith("ai_")


class AiConfigStore:
  def __init__(self, path: Path | None = None) -> None:
    self._path = path or ai_config_path()
    self._schema = _build_schema()
    self._data: dict[str, str] | None = None
    self._lock = threading.Lock()
    self._migrated = False
    self._save_timer: threading.Timer | None = None
    self._save_thread: threading.Thread | None = None
    self._save_pending = False

  @property
  def path(self) -> Path:
    return self._path

  def _default_for(self, key: str) -> str | None:
    meta = self._schema.get(key)
    if meta is None:
      return "" if is_ai_param(key) else None
    return meta.get("default", "")

  def _param_type(self, key: str) -> str:
    return (self._schema.get(key) or {}).get("param_type", "STRING")

  def _large_path(self, key: str) -> Path:
    return self._path.parent / f"config.large.{key}.json"

  def _load_disk(self) -> dict[str, str]:
    if not self._path.is_file():
      return {}
    try:
      raw = self._path.read_text(encoding="utf-8")
      data = json.loads(raw)
      if not isinstance(data, dict):
        return {}
      out = {str(k): "" if v is None else str(v) for k, v in data.items() if is_ai_param(str(k))}
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
      out = {}
    # 合并大字段独立文件（旧 config.json 里的大字段仍在 data 中，会被后续写盘拆分迁移）
    for key in _LARGE_KEYS:
      path = self._large_path(key)
      if not path.is_file():
        continue
      try:
        val = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(val, str):
          out[key] = val
      except (OSError, json.JSONDecodeError, TypeError, ValueError):
        continue
    return out

  def _cleanup_stale_temp_files(self) -> None:
    parent = self._path.parent
    if not parent.is_dir():
      return
    for path in parent.glob(".ai_config_*"):
      try:
        path.unlink()
      except OSError:
        pass

  def _atomic_write(self, path: Path, payload: str) -> None:
    fd, tmp = tempfile.mkstemp(prefix=".ai_config_", dir=str(path.parent))
    try:
      with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(payload)
        f.flush()
      os.replace(tmp, path)
      try:
        os.chmod(path, 0o600)
      except OSError:
        pass
      try:
        os.chmod(path.parent, 0o700)
      except OSError:
        pass
    finally:
      if os.path.exists(tmp):
        try:
          os.unlink(tmp)
        except OSError:
          pass

  def _save_disk(self, data: dict[str, str]) -> None:
    self._path.parent.mkdir(parents=True, exist_ok=True)
    self._cleanup_stale_temp_files()
    main = {k: v for k, v in data.items() if k not in _LARGE_KEYS}
    large = {k: v for k, v in data.items() if k in _LARGE_KEYS}
    payload = json.dumps(main, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    self._atomic_write(self._path, payload)
    # 大字段独立文件：仅值变化时写（避免每次全量写 3MB+）
    for key, value in large.items():
      path = self._large_path(key)
      try:
        old = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
      except Exception:
        old = None
      if old != value:
        self._atomic_write(path, json.dumps(value, ensure_ascii=False))

  def _migrate_from_params_dir(self, data: dict[str, str]) -> None:
    params_dir = Path("/data/params/d")
    if not params_dir.is_dir():
      return
    for entry in params_dir.iterdir():
      if not entry.is_file() or not entry.name.startswith("ai_"):
        continue
      if entry.name in data:
        continue
      try:
        text = entry.read_text(encoding="utf-8", errors="replace").strip("\x00")
        if text:
          data[entry.name] = text
      except OSError:
        continue

  def _migrate_from_params_api(self, data: dict[str, str]) -> None:
    try:
      Params, UnknownKeyName = import_openpilot_params()
    except Exception:
      return
    p = Params()
    for key in self._schema:
      if key in data:
        continue
      try:
        val = p.get(key)
      except UnknownKeyName:
        continue
      except Exception:
        continue
      if val is None:
        continue
      if isinstance(val, bytes):
        val = val.decode("utf-8", errors="replace")
      data[key] = str(val)

  def _migrate_legacy_github_pat(self, data: dict[str, str]) -> None:
    if data.get(_AI_GITHUB_PAT_KEY, "").strip():
      return
    legacy = _LEGACY_GITHUB_PAT_PARAM
    params_dir = Path("/data/params/d")
    if params_dir.is_dir():
      legacy_file = params_dir / legacy
      if legacy_file.is_file():
        try:
          text = legacy_file.read_text(encoding="utf-8", errors="replace").strip("\x00").strip()
          if text:
            data[_AI_GITHUB_PAT_KEY] = text
            return
        except OSError:
          pass
    try:
      Params, UnknownKeyName = import_openpilot_params()
    except Exception:
      return
    p = Params()
    try:
      val = p.get(legacy)
    except UnknownKeyName:
      return
    except Exception:
      return
    if val is None:
      return
    if isinstance(val, bytes):
      val = val.decode("utf-8", errors="replace")
    text = str(val).strip()
    if not text:
      return
    data[_AI_GITHUB_PAT_KEY] = text
    try:
      p.remove(legacy)
    except Exception:
      pass

  def _ensure_migrated(self, data: dict[str, str]) -> None:
    if self._migrated:
      return
    self._migrate_from_params_dir(data)
    self._migrate_from_params_api(data)
    self._migrate_legacy_github_pat(data)
    self._migrated = True
    if data != self._load_disk():
      self._save_disk(data)

  def _ensure_loaded(self) -> dict[str, str]:
    if self._data is not None:
      return self._data
    with self._lock:
      if self._data is not None:
        return self._data
      data = self._load_disk()
      self._ensure_migrated(data)
      self._data = data
      return data

  def _schedule_save(self) -> None:
    """2026-08-27: 合并线程 + 节流异步写盘——事件循环零阻塞、防写放大。

    写盘线程循环：put 标记 pending 后合并处理；最小写盘间隔 1s 节流；
    写盘期间的新 put 只标 pending，写完继续处理（不会每次 put 都写）。
    内存读取始终最新，重启最多丢最近 1s 的配置写入。
    """
    with self._lock:
      self._save_pending = True
      if self._save_thread is not None and self._save_thread.is_alive():
        return
      self._save_thread = threading.Thread(target=self._save_loop, daemon=True)
      self._save_thread.start()

  def _save_loop(self) -> None:
    last_save = 0.0
    try:
      while True:
        with self._lock:
          pending = self._save_pending
          self._save_pending = False
          data = dict(self._data or {})
        if not pending:
          with self._lock:
            self._save_thread = None
          return
        now = time.monotonic()
        wait = _MIN_SAVE_INTERVAL - (now - last_save)
        if wait > 0:
          time.sleep(wait)
        try:
          if data:
            self._save_disk(data)
          last_save = time.monotonic()
        except Exception:
          pass
    finally:
      with self._lock:
        if self._save_thread is not None:
          self._save_thread = None

  def reload(self) -> None:
    with self._lock:
      if self._save_timer is not None:
        self._save_timer.cancel()
        self._save_timer = None
      self._save_pending = False
      self._data = None
      self._migrated = False

  def get(self, key: str, default: Any = None) -> Any:
    if not is_ai_param(key):
      raise ValueError(f"not an ai param: {key}")
    data = self._ensure_loaded()
    if key in data:
      return data[key]
    schema_default = self._default_for(key)
    if schema_default is not None:
      return schema_default
    return default

  def get_bool(self, key: str, default: bool = False) -> bool:
    val = self.get(key, None)
    if val is None:
      return default
    if isinstance(val, bool):
      return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")

  def put(self, key: str, value: Any) -> None:
    if not is_ai_param(key):
      raise ValueError(f"not an ai param: {key}")
    ptype = self._param_type(key)
    if ptype == "BOOL" or isinstance(value, bool):
      text = "1" if (bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "yes")) else "0"
    elif ptype == "INT":
      text = str(int(value))
    elif ptype == "FLOAT":
      text = str(float(value))
    elif value is None:
      text = ""
    else:
      text = str(value)
    with self._lock:
      data = dict(self._ensure_loaded())
      data[key] = text
      self._data = data
    self._schedule_save()

  def put_bool(self, key: str, value: bool) -> None:
    self.put(key, value)

  def remove(self, key: str) -> None:
    if not is_ai_param(key):
      raise ValueError(f"not an ai param: {key}")
    with self._lock:
      data = dict(self._ensure_loaded())
      if key in data:
        del data[key]
      self._data = data
    self._schedule_save()

  def all_keys(self) -> list[str]:
    data = self._ensure_loaded()
    keys = set(self._schema) | set(data)
    return sorted(k for k in keys if is_ai_param(k))

  def read_all(self) -> dict[str, str]:
    data = dict(self._ensure_loaded())
    for key, meta in self._schema.items():
      data.setdefault(key, meta.get("default", ""))
    return {k: data[k] for k in sorted(data) if is_ai_param(k)}


def get_config_store() -> AiConfigStore:
  global _store
  if _store is None:
    with _store_lock:
      if _store is None:
        _store = AiConfigStore()
  return _store


def reset_config_store_for_tests(path: Path | None = None) -> AiConfigStore:
  """Test helper: point store at a temp file."""
  global _store
  with _store_lock:
    _store = AiConfigStore(path=path)
    return _store
