# 故障排查

## 助手无响应 / 配置失败

- 确认 `manager` 已启动且 `aid` 进程在运行。
- 设置 → 模型：测试 API 连接；检查 Key 与模型名是否正确。
- PC 开发：确认 `openpilot` 根目录与 `ai/` 已集成（`POST /api/ai/integrate`）。

## 无法 Engage（辅助驾驶接合）

1. 使用 **run_health_check(scope=engage)** 或 Web 快捷「一键健康检查」。
2. 按检查项顺序处理：
   - **SecOC / 指纹**：丰田/雷克萨斯见 `secoc-toyota` 技能。
   - **Panda**：`panda_status`；C3 DOS 见 `c3-dos-panda` 与 [PANDA_FLASH.md](PANDA_FLASH.md)。
   - **摄像头 / LKAS**：`read_onroad_events`、`trip_review`。
3. 完整分诊工作流：`engage_triage`。

## Cabana 回放

| 现象 | 处理 |
|------|------|
| 0 报文 / 立刻结束 | 换有 qlog 的路线；必要时勾选「完整 rlog」 |
| 表格空白 after seek | 刷新面板或重连回放（已修复相对时间轴） |
| 缩略图不准 | 需路线含 `qRoadEncodeIdx`；否则按 60s 段粗对齐 |

## 网络 / OTA

- `network_diagnostics`、`guide_ota_update`、`ota_preflight_checklist`。
- 行驶中禁止写 Param 与 OTA 刷写。

## 日志

- `read_manager_log`、`grep_log`、开发页「报告与导出」。

详细设备说明见 [COMMA_DEVICES.md](COMMA_DEVICES.md)、[TROUBLESHOOTING 相关 OVERVIEW](OVERVIEW.md)。
