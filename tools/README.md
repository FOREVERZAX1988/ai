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

## 常用分析工具
- `scan_override_protocol.py` / `scan_override_neg.py` / `scan_neg_global.py`：超驰协议与负verz扫描
- `vz_corr.py`：verz 与 aEgo/vRel 相关性分析
- `scan_verz_dist.py` / `scan_loes_conflict.py`：verz分布 / loes冲突
- `route_global_offset.py`：route时间全局偏移换算（glob需带hash段）

## 说明
- rlog 扫描禁止一次加载30分钟全量：按段(grep/glob)或Pool并行，超时按制度当场优化
- 位定义以 vw_mlb.dbc BO_269 帧内信号为准（ACC_Status_ACC=57|3 非 60|3）
- CAN消息 src 编号（Discord 权威）：0/1/2=在CAN0/1/2接收；128/129/130=发送/转发到CAN0/1/2；192/193/194=被Panda安全校验丢弃
