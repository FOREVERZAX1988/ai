"""Import cereal whichever way this tree exposes it.

Upstream openpilot keeps ``cereal`` at the repository root, so ``from cereal import
messaging`` works there. This fork is a monorepo that keeps the openpilot tree one level
down and imports it as a package -- its own code says ``openpilot.cereal`` (see
``openpilot/system/manager/manager.py``), so a bare top-level ``cereal`` module does not
exist on the device and every ``from cereal import ...`` in this package silently failed.
The visible symptom was the state reader being disabled: ``aid: cereal.messaging not
available (state reader disabled)`` and every vehicle snapshot coming back empty
(``reader_unavailable: true``), which is easy to mistake for "the car is off".

Try the package form first, then the upstream form, so the same source also works on a
plain upstream checkout.
"""

from __future__ import annotations

import importlib
from types import ModuleType

_PREFIXES = ("openpilot.cereal", "cereal")


def import_cereal(submodule: str = "") -> ModuleType:
  """Return ``cereal`` or ``cereal.<submodule>`` for the tree we are running in.

  Raises ImportError when neither form is importable, mirroring a plain
  ``from cereal import <submodule>``.
  """
  errors: list[str] = []
  for prefix in _PREFIXES:
    target = f"{prefix}.{submodule}" if submodule else prefix
    try:
      return importlib.import_module(target)
    except ImportError as exc:
      errors.append(f"{target}: {exc}")
  raise ImportError(
    f"cereal{('.' + submodule) if submodule else ''} is not importable in this tree "
    f"({'; '.join(errors)})"
  )
