# 调参指南

op助手面向**通用 openpilot**（非单一 fork）。调参前请 offroad，改参后封闭场地验证。

## 流程建议

1. **快照**：`save_tune_snapshot` 或 Web 调参护照记录。
2. **小步修改**：优先 `list_sp_settings` / `read_params`，一次只改少量相关 Param。
3. **验证**：`compare_tune_ab`、`score_tune_session`、`route_event_timeline`。
4. **回滚**：`restore_tune_snapshot` 或调参护照中的历史记录。

## 横向（ALKA / 车道保持）

- 技能：`alka-troubleshooting`、`sp-tuning`。
- 关注：MADS、`LiveTorque`、转向延迟、路线 `car_porting_steering_accuracy`。

## 纵向（跟车）

- 技能：`longitudinal-tuning`。
- 关注：跟车距离、加减速曲线、限速辅助（`sp-speed-limit`）。

## 品牌差异

按 CarParams 品牌启用对应 `sp-brand-*` 技能；丰田 SecOC 单独走 `secoc-toyota`。

## 工具

- `snapshot_tune_state`、`diff_params`、`apply_sp_tune_preset`
- 路线：`suggest_tune_from_route`、`apply_tune_from_route`（预览后确认）

调参记录可在 **设置 → 平台 → 调参护照** 查看时间线。
