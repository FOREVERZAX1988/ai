# 子模块指针审计（2026-10-21）——「指针对齐」这条待办的前提是错的，别按字面做

待办第 6 条原文：**「子模块指针对齐：panda d84b110fc→a4806cea4、opendbc ee86beb36→f087c437f、
rednose 8671c17c3→28d4a7f69（丢弃 LF 提交）」**。执行前核了一遍，两个前提都不成立：

## 一、opendbc 的起点编号已经过期

`git submodule status` 现在报的是 **9afcc5a6c**，不是 `ee86beb36`。`ee86beb36` 是「mazda:
Oceania VIN no longer crashes card at startup」，它之后我们分支又走了两条
（`ac1ac7c7a` 补 BYD 块逗号、`9afcc5a6c` 补 `_vehicle_speed_camera_distance_time` 的
`@staticmethod`）——**都是手工搬的 mouxangithub/opendbc 提交**（f06251665f、85095af0c）。

## 二、三个目标 SHA 没有一个是我们 pin 的后代

天真的「挪指针」= 直接换成另一条线的树。祖先关系实测：

| 子模块 | 我们的 pin | 目标 SHA | 我们 pin 是目标祖先？ | 目标在哪些分支 |
|---|---|---|---|---|
| panda | `d84b110fc` | `a4806cea4` | **否**（merge-base `74a0adced`） | `mouxan/master`、`up/master` |
| opendbc | `9afcc5a6c` | `f087c437f` | **否**（merge-base `3407ec3dc`） | `up/test`、`upstream/test` |
| rednose | `8671c17c3` | `28d4a7f69` | **否** | — |

之前那句「落后 23 / 3 / 76 条」是 `rev-list --count <我们的>..<目标>` 的误读：
它数的是「目标可达而我们不可达」的提交，**不等于快进**。改成反向再数才是我们会丢的东西。

## 三、按字面挪指针会丢什么（实测）

| 子模块 | 我们独有的提交 | 我们独有的文件 |
|---|---|---|
| **opendbc** | **279** | **7 个，全部是 Macan 适配**：`sunnypilot/car/volkswagen/{macan_calib,stop_and_go,values_ext}.py`、`car/volkswagen/tests/test_macan_mlb.py`、`sunnypilot/car/params_access.py`、`dbc/mazda_2019.dbc`、`sunnypilot/car/volkswagen/__init__.py` |
| panda | 2（`适配F4`、`加强适配c3`） | 160 个文件的差异主要是对方线的 UART/jungle 清理，不是我们的内容 |
| rednose | 1（`Use LF line endings`） | 无 |

opendbc 的 279 条里有 MLB EPS 故障判定位、capnp 合并残留修复、Toyota SecOC BSM、
lateral_tune 重构等等——丢一条都是回归，更别说整份 Macan 标定。

## 四、上游那三条到底有没有新东西？没有

`git diff --name-status 9afcc5a6c..f087c437f | grep '^A'` → **空**：目标分支**没有任何我们缺的文件**。
反方向有 7 个（上表）。且那 3 条独有提交里，`57fa48177`（mazda Oceania VIN）与
`c643cfcc9`（mazda ON press rearms MADS）就是我们已经手工搬过的 `ee86beb36` / `89e908293`
同一内容；`f087c437f 适配c3` 里的 BYD 车型包、`hyundai/radar_group3.py`、`radar_tracks.py`、
`radar_lead_filter.py` 在我们分支**都已存在**。

结论：**opendbc 无内容可拉，我们是超前的一方。**

## 五、所以正确做法

- **不要**在子模块里 `git checkout <目标 SHA>`。要同步就 `git merge <上游分支>` 进我们 fork 的分支，
  让 Macan 适配以「保留」的形态带过去。
- panda 若要跟上上游那条清理线，只有 `适配F4`、`加强适配c3` 两条需要保；同样用 merge，不用挪指针。
- 这条待办本身按「无操作 + 留证据」收口。
