"""校验子模块可达性：主仓记录的每个 submodule commit，能否从 .gitmodules 声明的 URL 拉到。

`git submodule update --init --recursive` checkout 的是记录的 SHA，不是分支名。
那个 SHA 只要不在远端的任何 ref 里，GitHub 就回
"upload-pack: not our ref / Fetched in submodule path 'x', but it did not contain <sha>"，
设备上的更新从此**永久失败**（2026-10-30 的 mici .45：UpdateFailedCount=12，
屏幕上表现为「一直有更新、一直装不上」；原因是我们把 opendbc 的 pin 指向了一个
只在本地存在、从未推到 fork 的 commit）。

用起来：

    python ai/tools/check_submodule_pins.py     # 退出码非 0 就是有人把 unreachable 的 SHA 写进了主仓

推送每个子模块之后都该跑一次 —— push 主仓而漏掉子模块是最容易犯的那种错：
本地一切正常，因为本地 checkout 里本来就有那些对象。
"""
import concurrent.futures
import shutil
import subprocess
import sys
import tempfile

ROOT = "/Users/zzz/Desktop/workspace/openpilot"


def git(*args, cwd=ROOT, check=True, timeout=120):
  return subprocess.run(("git",) + args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=check)


def parse():
  cfg = git("config", "-f", ".gitmodules", "-l").stdout
  subs = {}
  for line in cfg.splitlines():
    k, _, v = line.partition("=")
    parts = k.split(".")
    if len(parts) == 3 and parts[0] == "submodule":
      subs.setdefault(parts[1], {})[parts[2]] = v
  for name, info in subs.items():
    out = git("ls-tree", "HEAD", info["path"]).stdout.split()
    info["sha"] = out[2] if len(out) >= 3 else None
  return subs


def reachable(info):
  d = tempfile.mkdtemp(prefix="sm-")
  try:
    subprocess.run(("git", "init", "-q", d), check=True)
    subprocess.run(("git", "-C", d, "remote", "add", "o", info["url"]), check=True)
    r = subprocess.run(("git", "-C", d, "fetch", "-q", "--depth", "1", "o", info["sha"]),
                       capture_output=True, text=True, timeout=300)
    return r.returncode == 0, (r.stderr or "").strip().splitlines()[:1]
  finally:
    shutil.rmtree(d, ignore_errors=True)


def main():
  subs = parse()
  bad = []
  with concurrent.futures.ThreadPoolExecutor(max_workers=len(subs)) as pool:
    futures = {pool.submit(reachable, info): name for name, info in subs.items()}
    for fut in concurrent.futures.as_completed(futures):
      name = futures[fut]
      info = subs[name]
      try:
        ok, err = fut.result()
      except Exception as e:
        ok, err = False, [str(e)[:120]]
      sha = (info["sha"] or "?")[:10]
      if ok:
        print(f"  ✅ {name:24s} {sha}  可从 {info['url']} 取到")
      else:
        bad.append(name)
        print(f"  ❌ {name:24s} {sha}  取不到 <- {info['url']}\n       {(err[0] if err else '')[:160]}")
  print()
  if bad:
    print(f"结果：{len(subs) - len(bad)} 通过 / {len(bad)} 失败   <- 这些会让设备上的更新直接失败：{', '.join(bad)}")
    return 1
  print(f"结果：{len(subs)} 个子模块的 pin 全部可从远端取到")
  return 0


if __name__ == "__main__":
  sys.exit(main())
