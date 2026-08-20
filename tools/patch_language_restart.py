#!/usr/bin/env python3
"""为 device.py 语言切换后添加"重启UI/重启系统"确认框（防切语言空白兜底）"""
import sys

path = "/data/openpilot/openpilot/selfdrive/ui/layouts/settings/device.py"
s = open(path, encoding="utf-8").read()

# 1. 加 import subprocess
old_imp = "import os\nimport math\n"
new_imp = "import os\nimport math\nimport subprocess\n"
if "import subprocess" not in s:
    assert old_imp in s, "imports 定位失败"
    s = s.replace(old_imp, new_imp, 1)
    print("OK: +import subprocess")

# 2. 加 from openpilot.common.hardware import HARDWARE
old_imp2 = "from openpilot.common.basedir import BASEDIR\n"
new_imp2 = "from openpilot.common.basedir import BASEDIR\nfrom openpilot.common.hardware import HARDWARE\n"
if "from openpilot.common.hardware import HARDWARE" not in s:
    assert old_imp2 in s, "HARDWARE import 定位失败"
    s = s.replace(old_imp2, new_imp2, 1)
    print("OK: +HARDWARE import")

# 3. handle_language_selection：切语言后弹重启确认框
old_block = """        multilang.change_language(selected_language)
        gui_app.on_language_changed(selected_language)
        self._update_calib_description()
      self._select_language_dialog = None"""
new_block = """        multilang.change_language(selected_language)
        gui_app.on_language_changed(selected_language)
        self._update_calib_description()
        # 语言切换后弹重启确认（防渲染空白兜底）：确认=重启UI，取消=重启系统。
        # 若屏幕文字空白，按钮色块仍可见可点（右侧高亮=重启UI）。
        gui_app.push_widget(ConfirmDialog(
          tr("Language changed. Restart UI to apply?\\nIf the screen is blank, tap the highlighted button."),
          confirm_text=tr("Restart UI"),
          cancel_text=tr("Reboot Device"),
          callback=self._handle_language_restart,
        ))
      self._select_language_dialog = None"""
assert old_block in s, "handle_language_selection 定位失败"
s = s.replace(old_block, new_block, 1)
print("OK: +语言切换后重启确认框")

# 4. 新增 _handle_language_restart 方法（插在 _reset_calibration_prompt 前）
anchor = "  def _reset_calibration_prompt(self):"
method = """  def _handle_language_restart(self, result: DialogResult):
    # ui 进程 restart_if_crash=True，pkill 后 manager 会自动拉起
    if result == DialogResult.CONFIRM:
      subprocess.run(["pkill", "-f", "openpilot.selfdrive.ui.ui"], check=False)
    else:
      HARDWARE.reboot()

"""
assert anchor in s, "方法插入锚点定位失败"
s = s.replace(anchor, method + anchor, 1)
print("OK: +_handle_language_restart 方法")

open(path, "w", encoding="utf-8").write(s)
print("写入完成")
