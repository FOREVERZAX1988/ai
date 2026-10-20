# 2026-10-21 Web Push 状态回归 Params（+ SConstruct 固定 -O0 收口）

## 为什么这次能搬

10-20 落地 PWA/Web Push 时，`libparams_c.so` 重建在这台机子上过不去（lowmemorykiller
反复 SIGKILL `clang++`），所以 VAPID 密钥对与浏览器订阅被放进
`/data/carrot/state/web_push.json`，代价是**不进 Params 备份**。现在重建路径通了
（`SConstruct` 对 `params.cc` 固定 `-O0`，见
`libparams_c_rebuild_recipe_20261021.md`），就按驾驶者当时的决定搬回注册表。

## 改了什么

| 文件 | 改动 |
|---|---|
| `openpilot/common/params_keys.h` | 新增 `WebPushVapid`、`WebPushSubscriptions`（`PERSISTENT \| BACKUP`, `JSON`），紧跟在本地 `CustomKp` 块后 |
| `.../carrot/server/services/web_push.py` | `load_state()/save_state()` 改为读写上面两个键（`block=True`），保留「一次迁移」逻辑 |
| `.../carrot/server/config.py` | `CARROT_WEB_PUSH_PATH` 降级为**旧文件路径**，只用于迁移 |
| `.../server/tests/test_web_push.py` | 新增 `_FakeParams`：测试只碰内存，不再碰设备 Params；补迁移用例 |

迁移语义：`load_state()` 发现两个键都是空 **且** `web_push.json` 还在 → 把文件内容
写进 Params，然后 `os.replace` 成 `web_push.json.migrated`（留作备份，只跑一次）。
所以手机上已经订阅好的浏览器不会被这次搬家作废。

## 实测证据（真机，非 mock）

```
keys count: 673                      # 搬之前 671（+2 新键）
CustomKp          type=3 (FLOAT)
WebPushVapid      type=5 (JSON)
WebPushSubscriptions type=5 (JSON)
```

迁移前后对照（VAPID 公钥与订阅数）：

```
迁移前 /data/carrot/state/web_push.json:
  vapid pub = BL6I2ebTp45MdPAuEhugTDtDspji_Tw5_KwB8SJP1PlNlmZFTx67V-okAaojLSNQc-kaT65a27jR1JmPU9fitrE
  subs      = 2  (https://jmt17.google.com/fcm/send/... 手机 Chrome；https://wns2-sg2p.notify.windows.com/... 桌面 Edge)
迁移后 Params: 同公钥、2 条订阅；文件已改名 web_push.json.migrated（1306 B，保留）
迁移后 GET http://127.0.0.1:7000/api/push/status:
  {"vapidPublicKey":"BL6I2ebTp45MdPAuEhug...fitrE","subscriptions":2}
```

## 测试

```
pytest openpilot/sunnypilot/carrot/server/tests             146 passed, 48 skipped
pytest openpilot/sunnypilot/carrot/server/tests/test_web_push.py   10 passed
pytest openpilot/sunnypilot/carrot/tests                    688 passed, 6 skipped
ai/scripts/upstream_divergence_check.py                     23/23 + 7/7, 无 DRIFT
```

`_FakeParams` 是必须的：这两条测试如果在车机上直接打真 Params，会覆写手机正在用的
VAPID 密钥对（`ensure_vapid_keys()` 首次调用会生成新密钥），等于把已装好的 Push 打死。

## 注意（下次别踩）

- 加键之后两步才能真生效：**重建 `.so`** + `sudo systemctl restart comma`（manager
  自己 import 过 params，子进程继承的是它的旧 mmap，只重启 carrot_server 没用）。
- 迁移只在「两个键都为空」时触发；如果哪天手动清过 Params 但 `.migrated` 还在，
  不会二次回灌（这是有意的：避免旧数据复活）。
