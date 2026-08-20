#!/usr/bin/env python3
"""patch3：修复"取消不是真取消"——先确认再切换语言
逻辑：选语言后先弹确认框；取消=不切换（保持原语言）；确定=切换+自动重启UI"""
import sys

path = "/data/openpilot/openpilot/selfdrive/ui/layouts/settings/device.py"
s = open(path, encoding="utf-8").read()

# 1. handle_language_selection：确认框提到切换之前
old1 = """      if result == DialogResult.CONFIRM and self._select_language_dialog:
        selected_language = multilang.languages[self._select_language_dialog.selection]
        multilang.change_language(selected_language)
        gui_app.on_language_changed(selected_language)
        self._update_calib_description()
        # 语言切换后弹确认框（防渲染空白兜底）：确定=重启UI，取消=不操作
        gui_app.push_widget(ConfirmDialog(
          tr("Language changed. Restart the UI to apply."),
          confirm_text=tr("OK"),
          cancel_text=tr("Cancel"),
          callback=self._handle_language_restart,
        ))"""
new1 = """      if result == DialogResult.CONFIRM and self._select_language_dialog:
        selected_language = multilang.languages[self._select_language_dialog.selection]
        # 先确认再切换：确定=切换语言+重启UI，取消=保持原语言（避免切换后空白无法恢复）
        gui_app.push_widget(ConfirmDialog(
          tr("Language changed. Restart the UI to apply."),
          confirm_text=tr("OK"),
          cancel_text=tr("Cancel"),
          callback=lambda r: self._apply_language_selection(selected_language, r),
        ))"""
assert old1 in s, "handle_language_selection 块未匹配"
s = s.replace(old1, new1, 1)
print("OK: 确认框已移到切换之前（先问再切）")

# 2. 方法替换：_handle_language_restart → _apply_language_selection
old2 = """  def _handle_language_restart(self, result: DialogResult):
    # 确定=重启UI（ui 进程 restart_if_crash=True，pkill 后 manager 自动拉起）；取消=不操作
    if result == DialogResult.CONFIRM:
      subprocess.run(["pkill", "-f", "openpilot.selfdrive.ui.ui"], check=False)"""
new2 = """  def _apply_language_selection(self, selected_language: str, result: DialogResult):
    # 取消=不切换（保持原语言）；确定=切换语言并重启 UI（防字体热重载空白）
    if result != DialogResult.CONFIRM:
      return
    multilang.change_language(selected_language)
    gui_app.on_language_changed(selected_language)
    self._update_calib_description()
    # ui 进程 restart_if_crash=True，pkill 后 manager 自动拉起
    subprocess.run(["pkill", "-f", "openpilot.selfdrive.ui.ui"], check=False)"""
assert old2 in s, "方法块未匹配"
s = s.replace(old2, new2, 1)
print("OK: 方法替换为 _apply_language_selection（取消=不切换）")

# 3. 移除不再使用的 HARDWARE import
old3 = "from openpilot.common.hardware import HARDWARE\n"
assert old3 in s, "HARDWARE import 未找到"
s = s.replace(old3, "", 1)
print("OK: 移除未使用的 HARDWARE import")

open(path, "w", encoding="utf-8").write(s)
print("写入完成")
