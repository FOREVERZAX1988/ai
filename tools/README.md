# ai/tools — op 助手工具目录

所有诊断/分析脚本统一放本目录（用户制度：参数化、带README、禁止散落 /tmp）。
用法示例见各脚本 docstring；均支持 `python3 <script>.py --help` 或裸跑打印用法。

## 本次会话新增工具（2026-08-29）
| 工具 | 用途 | 用法 |
|---|---|---|
| `scan_ovr_transparent.py` | 超驰(st=4)窗口透传验证：当前OP帧vs原厂帧差值 + 模拟透传后残余差值 | `python3 scan_ovr_transparent.py 0000004e 0000004f` |
| `scan_st6_idx.py` | st6事件 × Abstandsindex(ACC_02) 相关性验证 | `python3 scan_st6_idx.py ROUTE [ROUTE...]` |
| `scan_mm_window.py` | 原厂监管窗口(idx阈值)反向验证：idx<200 vs ≥200 差异帧统计 | `python3 scan_mm_window.py ROUTE [ROUTE...]` |
| `restart_aid.sh` | 无人值守重启 ai.aid（持久日志 /data/ai/logs/aid.log） | `nohup bash restart_aid.sh 60 &` |

## 本次会话新增工具（2026-08-29 补充）
| 工具 | 用途 | 用法 |
|---|---|---|
| `corr_axg_mom_lag.py` | axG 与 mom 时序相关性（同帧+滞后窗口，标准DBC解析；修正旧 corr_axg_verz_mom.py 位序bug） | `python3 corr_axg_mom_lag.py ROUTE [--seg N] [--lagmax N]` |

## 本次会话新增工具（2026-08-29 补充2）
| 工具 | 用途 | 用法 |
|---|---|---|
| `scan_st6_sig.py` | st6 事件 OP帧vs原厂帧 三信号差异分析（verz/mom/axG 执行反馈矛盾定位） | `python3 scan_st6_sig.py ROUTE [--seg N M] [--window N]` |

## 常用分析工具
- `scan_override_protocol.py` / `scan_override_neg.py` / `scan_neg_global.py`：超驰协议与负verz扫描
- `vz_corr.py`：verz 与 aEgo/vRel 相关性分析
- `scan_verz_dist.py` / `scan_loes_conflict.py`：verz分布 / loes冲突
- `route_global_offset.py`：route时间全局偏移换算（glob需带hash段）

## 说明
- rlog 扫描禁止一次加载30分钟全量：按段(grep/glob)或Pool并行，超时按制度当场优化
- 位定义以 vw_mlb.dbc BO_269 帧内信号为准（ACC_Status_ACC=57|3 非 60|3）
- CAN消息 src 编号（Discord 权威）：0/1/2=在CAN0/1/2接收；128/129/130=发送/转发到CAN0/1/2；192/193/194=被Panda安全校验丢弃

## brake_classify.py — braking输出健康度分类
分析route里OP的减速请求(verz<0)：分类真减速/阈值抖动/其他，输出占比+健康度建议。
用法：`python3 ai/tools/brake_classify.py 00000066 [--seg 10] [--min-frames 3] [--verbose]`
阈值抖动>30%提示braking滞回未生效或planner噪声（对照：0066全route 40%帧/229窗口/真减速51%/阈值抖动35%——滞回修复前）。

## 设备 `.79` 上跑仿真的正确口径（2026-11-08 定稿）

历史上多次「仿真假失败」都源于环境口径不对，不是代码回归：

| 项 | 正确值 | 踩过的坑 |
|---|---|---|
| Python | `/usr/local/venv/bin/python` | `/usr/bin/python3` 是系统 Python，没有 `raylib_nb` / `nanobind` / `pytest` |
| pip 依赖目录 | `PYTHONPATH=/data/.pydeps` | 这是 `launch_chffrplus.sh` 的 `PYDEPS_DIR`（注释：放在 `$DIR` 外，overlay 更新不会清掉）。**不要**用 `/data/tmp/pydeps`，它会被清掉 → 缺 `pytest`/`aiohttp` → 按键组失败、`carrot_webrtcd` 假报 import 断链 |
| VW safety | 必须带 `SAFETY_NO_SANITIZERS=1` | AGNOS 工具链缺 UBSan runtime，`libsafety.so` 在 `setUp` 阶段 dlopen 失败 → 成片 F，与代码无关 |
| 编译 | `PATH=/usr/local/venv/bin:$PATH PYTHONPATH= scons -j2` | `-j4` 会 OOM；`PYTHONPATH` 带 pydeps 会污染构建 |
| 仿真入口 | `PYTHONPATH=/data/.pydeps <venv-python> ai/tools/sim_test_macan.py` | 判据看 `SIM_EXIT=0` |

`boot_smoke_test.py` 的 import 判据在**非 Linux 开发机**上会精确豁免
`Params("/dev/shm/params")` 造成的 `Failed to ensure params path`（macOS 无 `/dev/shm`），
并显式打印为 `[平台限制]`；Linux 设备上同样错误仍是硬错，其它 import 异常一律照旧失败。
`OPTIONAL_MODULES`（Lite beepd / USE_WEBCAM camerad）的失败会带上原因文案，属预期。

设备 `.git/hooks/post-merge` 在没有 `git-lfs` 时原本 `exit 2` 并刷警告，已改为静默
`exit 0`（若装了 git-lfs 仍会执行 `git lfs post-merge`），原文件备份为
`.git/hooks/post-merge.lfs-bak`。
