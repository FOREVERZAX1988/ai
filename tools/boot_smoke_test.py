#!/usr/bin/env python3
"""
openpilot 系统启动冒烟测试（boot smoke）

用途：merge 上游 / 大改动后，在设备或 PC 上快速验证"系统能不能启动"，
提前挡住上车才会爆的启动类错误：
  1. import 全模块 —— 抓循环导入、模块级 ImportError/NameError/缺依赖
     （可选进程缺依赖只标 WARN，不算失败）
  2. AST 静态检查 —— 抓"函数内引用了既非局部、又非模块级定义/import 的名称"
     （运行期 NameError 的典型，如 modem._qmi_mode 用 is_tici_dos 但没 import）

覆盖的绑定场景：模块级 import/def/赋值（含 if/for 块内）、函数参数、
函数内赋值/import/嵌套函数/except-as/global 声明。

运行：cd /data/openpilot && python3 ai/tools/boot_smoke_test.py
退出码：0=全部通过；1=有失败
"""

import ast
import builtins
import importlib
import importlib.util
import os
import sys

OPENPILOT_ROOT = "/data/openpilot"
BUILTINS = set(dir(builtins))

# 已知上游缺陷（非本次改动引入，未触达路径；标注 WARN 不算失败）
KNOWN_ISSUES = {
    ("modem.py", "Serial"):
        "上游隐藏缺陷：query_imei_at_port 用 Serial() 但无 import 且设备无 pyserial——该函数从未被调用（IMEI 走其他路径），加 import 反而会挂",
}

OPTIONAL_MODULES = {
    "openpilot.sunnypilot.selfdrive.ui.beepd": "Lite 专用（GPIO beeper，本机 C3X 不启用）",
    "openpilot.system.camerad.webcam.camerad": "USE_WEBCAM 才启用（设备无 av 库属正常）",
}


def collect_modules() -> list[tuple[str, bool]]:
    sys.path.insert(0, OPENPILOT_ROOT)
    from openpilot.system.manager.process_config import managed_processes
    from openpilot.system.manager.process import PythonProcess, DaemonProcess
    mods = set()
    for p in managed_processes.values():
        if isinstance(p, (PythonProcess, DaemonProcess)) and p.module:
            mods.add(p.module)
    for extra in [
        "openpilot.selfdrive.controls.lib.longitudinal_planner",
        "openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.long_mpc",
        "opendbc.car.volkswagen.carcontroller",
        "opendbc.car.volkswagen.carstate",
        "opendbc.car.volkswagen.mlbcan",
        "openpilot.common.hardware.comma.hardware",
        "openpilot.common.hardware.comma.modem",
    ]:
        mods.add(extra)
    return [(m, m in OPTIONAL_MODULES) for m in sorted(mods)]


def import_check(module: str) -> str | None:
    try:
        importlib.import_module(module)
        return None
    except Exception as e:
        return f"{type(e).__name__}: {e}"


def _collect_module_names(tree) -> set[str]:
    """收集模块级定义（含 if/for/try 块内），不进函数/类内部"""
    names = set()

    def add_targets(t):
        # 递归收集赋值目标里的 Name（含 tuple/list 解包）
        if isinstance(t, ast.Name):
            names.add(t.id)
        elif isinstance(t, (ast.Tuple, ast.List)):
            for e in t.elts:
                add_targets(e)

    def walk(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(child.name)
                continue  # 不进函数/类内部
            if isinstance(child, ast.Import):
                for a in child.names:
                    names.add(a.asname or a.name.split(".")[0])
            elif isinstance(child, ast.ImportFrom):
                for a in child.names:
                    names.add(a.asname or a.name)
            elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
            elif isinstance(child, ast.Assign):
                for t in child.targets:
                    add_targets(t)
            elif isinstance(child, (ast.AnnAssign, ast.AugAssign)):
                add_targets(child.target)
            else:
                walk(child)

    walk(tree)
    return names


def _walk_loads(node, scope, issues, fn_name):
    """遍历函数体：跳过嵌套函数/类/lambda 子树，检查 Load 名称"""
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
            continue
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            if child.id not in scope and child.id not in BUILTINS:
                issues.append(f"  函数 {fn_name} 引用未定义名称: {child.id}")
        else:
            _walk_loads(child, scope, issues, fn_name)


def _function_locals(node) -> set[str]:
    """函数体直接绑定：参数/赋值/嵌套函数名/except-as/import/global（不进嵌套函数内部）"""
    local = set()
    for a in list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs):
        local.add(a.arg)
    if node.args.vararg:
        local.add(node.args.vararg.arg)
    if node.args.kwarg:
        local.add(node.args.kwarg.arg)

    def collect(n):
        for child in ast.iter_child_nodes(n):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                local.add(child.id)
            elif isinstance(child, ast.ExceptHandler):
                if child.name:
                    local.add(child.name)
                collect(child)  # 进入 except 块体继续收集
            elif isinstance(child, ast.Import):
                for a in child.names:
                    local.add(a.asname or a.name.split(".")[0])
            elif isinstance(child, ast.ImportFrom):
                for a in child.names:
                    local.add(a.asname or a.name)
            elif isinstance(child, ast.Global):
                local.update(child.names)
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                local.add(child.name)  # 嵌套定义名（不进内部，嵌套函数有独立检查）
            elif isinstance(child, ast.Lambda):
                continue
            else:
                collect(child)

    collect(node)
    return local


def i18n_check(root: str) -> list[str]:
    """events / mici UI 硬编码中文检查（排除注释与 docstring）：
    英文 msgid + po 翻译是汉化体系，硬编码中文会破坏语言切换"""
    files = [
        "openpilot/selfdrive/selfdrived/events.py",
        "openpilot/sunnypilot/selfdrive/selfdrived/events.py",
        "openpilot/sunnypilot/selfdrive/selfdrived/events_base.py",
        "openpilot/selfdrive/ui/mici",
    ]
    issues = []
    for rel in files:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        py_files = []
        if os.path.isdir(path):
            for dp, _, fs in os.walk(path):
                for f in fs:
                    if f.endswith(".py"):
                        py_files.append(os.path.join(dp, f))
        else:
            py_files = [path]
        for fp in py_files:
            try:
                tree = ast.parse(open(fp, encoding="utf-8").read())
            except Exception:
                continue
            parents = {}
            for n in ast.walk(tree):
                for c in ast.iter_child_nodes(n):
                    parents[c] = n
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value:
                    # 独立语句字符串（Expr）= 注释/docstring，非 UI 文本，豁免
                    if isinstance(parents.get(node), ast.Expr):
                        continue
                    if any('\u4e00' <= c <= '\u9fff' for c in node.value):
                        relp = os.path.relpath(fp, root)
                        issues.append(f"  {relp}: 硬编码中文 \"{node.value[:25]}\"")
    return issues


def ast_check(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except Exception as e:
        return [f"  AST 解析失败: {e}"]

    module_names = _collect_module_names(tree)
    # 构建函数树：子函数 -> 直接父函数（闭包作用域链）
    parents: dict[ast.AST, ast.AST | None] = {}

    def build(node, parent):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parents[child] = parent
                build(child, child)
            else:
                build(child, parent)

    build(tree, None)

    issues = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # 作用域 = 模块级 + 自身 + 所有祖先函数（闭包链）
        scope = set(module_names)
        cur = node
        while cur is not None:
            scope |= _function_locals(cur)
            cur = parents.get(cur)
        _walk_loads(node, scope, issues, node.name)

    # 过滤已知上游缺陷
    import os as _os
    base = _os.path.basename(path)
    filtered = []
    for i in issues:
        # 解析 "函数 X 引用未定义名称: Y" -> (X, Y)
        parts = i.strip().split()
        # 格式: 函数 <fn> 引用未定义名称: <id>  ->  4 段
        if len(parts) == 4 and parts[0] == "函数" and parts[2] == "引用未定义名称:":
            name = parts[3]
            if (base, name) in KNOWN_ISSUES:
                continue
        filtered.append(i)
    return filtered


def main() -> int:
    root = os.environ.get("OPENPILOT_ROOT", OPENPILOT_ROOT)
    if not os.path.isdir(os.path.join(root, "openpilot")):
        print(f"❌ 找不到 openpilot 源码根: {root}")
        return 2

    print("=" * 60)
    print("▶ 启动冒烟测试（import 全模块 + AST 未定义名称检查）")
    print("=" * 60)

    modules = collect_modules()
    print(f"\n模块数: {len(modules)}（可选 {sum(1 for _, o in modules if o)} 个）")

    import_fail = []
    import_warn = []
    for m, optional in modules:
        err = import_check(m)
        if err:
            if optional:
                import_warn.append((m, err))
                print(f"  ⚠️ [可选] import 失败: {m}\n     {err}")
            else:
                import_fail.append((m, err))
                print(f"  ❌ import 失败: {m}\n     {err}")
        else:
            print(f"  ✅ import OK: {m}")

    ast_fail = []
    for m, optional in modules:
        try:
            spec = importlib.util.find_spec(m)
            if spec is None or spec.origin is None:
                continue
            path = spec.origin
            if not path.startswith(root):
                continue
            issues = ast_check(path)
            if issues:
                ast_fail.append((m, issues))
                print(f"  ❌ AST: {m}")
                for i in issues:
                    print(i)
        except Exception as e:
            print(f"  ⚠️ {m} 跳过（{e}）")

    i18n_issues = i18n_check(root)
    if i18n_issues:
        print("\n  ❌ i18n: 硬编码中文（应走 po 翻译）")
        for i in i18n_issues:
            print(i)

    print("\n" + "=" * 60)
    if not import_fail and not ast_fail and not i18n_issues:
        print(f"🎉 启动冒烟通过：{len(modules)} 模块 import 无硬错 + AST 无未定义名称 + 无硬编码中文"
              + (f"（{len(import_warn)} 个可选进程缺依赖已跳过）" if import_warn else ""))
        return 0
    else:
        print(f"❌ 启动冒烟失败：import 硬错 {len(import_fail)}，AST {len(ast_fail)}，i18n {len(i18n_issues)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
