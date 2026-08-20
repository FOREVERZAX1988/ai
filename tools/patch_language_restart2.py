#!/usr/bin/env python3
"""第二次 patch：语言切换确认框改标准样式（取消/确定）+ po 中文翻译"""
import sys

# ============ 1. device.py：文案+按钮改标准样式 ============
path = "/data/openpilot/openpilot/selfdrive/ui/layouts/settings/device.py"
s = open(path, encoding="utf-8").read()

old_block = """        # 语言切换后弹重启确认（防渲染空白兜底）：确认=重启UI，取消=重启系统。
        # 若屏幕文字空白，按钮色块仍可见可点（右侧高亮=重启UI）。
        gui_app.push_widget(ConfirmDialog(
          tr("Language changed. Restart UI to apply?\\nIf the screen is blank, tap the highlighted button."),
          confirm_text=tr("Restart UI"),
          cancel_text=tr("Reboot Device"),
          callback=self._handle_language_restart,
        ))"""
new_block = """        # 语言切换后弹确认框（防渲染空白兜底）：确定=重启UI，取消=不操作
        gui_app.push_widget(ConfirmDialog(
          tr("Language changed. Restart the UI to apply."),
          confirm_text=tr("OK"),
          cancel_text=tr("Cancel"),
          callback=self._handle_language_restart,
        ))"""
assert old_block in s, "确认框块未找到（可能已改过）"
s = s.replace(old_block, new_block, 1)
print("OK: 确认框改标准样式（OK/Cancel）")

old_method = """  def _handle_language_restart(self, result: DialogResult):
    # ui 进程 restart_if_crash=True，pkill 后 manager 会自动拉起
    if result == DialogResult.CONFIRM:
      subprocess.run(["pkill", "-f", "openpilot.selfdrive.ui.ui"], check=False)
    else:
      HARDWARE.reboot()
"""
new_method = """  def _handle_language_restart(self, result: DialogResult):
    # 确定=重启UI（ui 进程 restart_if_crash=True，pkill 后 manager 自动拉起）；取消=不操作
    if result == DialogResult.CONFIRM:
      subprocess.run(["pkill", "-f", "openpilot.selfdrive.ui.ui"], check=False)
"""
assert old_method in s, "方法体未找到"
s = s.replace(old_method, new_method, 1)
print("OK: 方法去掉 reboot 分支（取消=不操作）")

open(path, "w", encoding="utf-8").write(s)

# ============ 2. po：新文案中文翻译 ============
MSGID = "Language changed. Restart the UI to apply."
TRANS = {
    "openpilot/selfdrive/ui/translations/app_zh-CHS.po": ("更改语言需要重启UI。", "Change Language"),
    "openpilot/selfdrive/ui/translations/app_zh-CHT.po": ("更改語言需要重啟UI。", "Change Language"),
}
for pf, (msgstr, anchor) in TRANS.items():
    p = f"/data/openpilot/{pf}"
    t = open(p, encoding="utf-8").read()
    if f'msgid "{MSGID}"' in t:
        print(f"[跳过] {pf.split('/')[-1]}: 已存在")
        continue
    assert f'msgid "{anchor}"' in t, f"{pf}: 锚点缺失"
    block = f'msgid "{MSGID}"\nmsgstr "{msgstr}"\n\n'
    t = t.replace(f'msgid "{anchor}"', block + f'msgid "{anchor}"', 1)
    open(p, "w", encoding="utf-8").write(t)
    print(f"OK: {pf.split('/')[-1]} +1条")

# ============ 3. 验证 ============
sys.path.insert(0, "/data/openpilot")
from pathlib import Path
from openpilot.system.ui.lib.multilang import load_translations
for pf in TRANS:
    fn = pf.split("/")[-1]
    trs, _ = load_translations(Path(f"/data/openpilot/{pf}"))
    ok = MSGID in trs and "OK" in trs and "Cancel" in trs
    print(f"[验证] {fn}: 新文案={'✅' if MSGID in trs else '❌'} OK={'✅' if 'OK' in trs else '❌'} Cancel={'✅' if 'Cancel' in trs else '❌'}")
print("全部完成")
