#!/usr/bin/env python3
"""更新 ai_todos/todos.json：标记已完成 + 追加 10-08 路试结论与融合层新发现。"""
import json
import time

P = "/data/openpilot/ai_todos/todos.json"
d = json.load(open(P, encoding="utf-8"))
items = d["todos"]


def find(sub):
    for it in items:
        if sub in it["content"]:
            return it
    return None


# 1) 已落地：idx→米 同源收敛（commit e945980eea + stop_and_go 改走 macan_calib）
it = find("idx→米 换算同源")
if it:
    it["status"] = "completed"
    it["content"] += "  ｜10-09 已落地：radard A2 / radar_interface A3 / stop_and_go 门 全部改走 opendbc/sunnypilot/car/volkswagen/macan_calib.py 单一源（旧 0.0424 线性近似已删）。"

# 2) 已落地：融合语义反转（视觉主导，雷达只能改近）
it = find("架构·丰田式")
if it:
    it["status"] = "completed"
    it["content"] += "  ｜10-09 已落地 commit af48eb247a（_macan_fuse_leads 改为视觉主导 + 原厂仅门内改近）。"

new = [
  {"content": "【已完成·10-08 路试】分支 sp-macanlong-dev 已推送：openpilot 19c41502c5 / opendbc df56dd1d3 / "
              "ai 9ae4ab2509 / webui 92e86674c2（四仓远端 refs/heads/sp-macanlong-dev 已核对一致）。",
   "status": "completed"},
  {"content": "【已完成·10-08 路试确认】①二次起步险撞未复现：全程 18 次停车→起步，engage 状态起步时融合车距最小 6.75 m"
              "（低速加车最小 4.58 m，且当时 vEgo≈0）；②idx 冻结时融合跟随视觉：seg11 t≈715 d_stock 冻结 26.52 m 达 14.1 s、"
              "视觉 6.5~7.4 m，融合 med 7.38 m（比冻结值低 19.1 m）；seg9 t≈618、seg5 t≈396、seg7 t≈505 同型。"
              "③无 critical 事件；仅 steerOverride×1043（人工转向）、wrongGear/reverseGear（泊车）。",
   "status": "completed"},
  {"content": "【⚠️新发现·高】融合层「低通 + 对称速率限幅」在前车重新捕获/距离跳变时会把 dRel 钉在远低于视觉值 1~2 s，"
              "制造幽灵近车→幽灵减速。证据（00000092 路试，d_vis / d_fus / a_cmd）：seg8 t≈579.8（78.9/25.9/−1.14）、"
              "seg13 t≈854.4（62.1/12.4）、seg11 t≈774.8（87.8/19.6）、seg12 t≈775.2（90.6/35.5/−1.10）、seg4 t≈352.8（66.8/17.1）。"
              "量化：engage&视觉可用 7045 帧中，融合比视觉近 >5 m 共 740 帧（10.5%），其中仅 33.6% 能用「原厂新鲜 idx 过门采纳」解释，"
              "96% 为滤波/限幅伪影，86 帧伴随指令减速。根因：①`if not lead.present: continue` 使 filter 与 _macan_last_fused 状态冻结，"
              "重捕获首帧直接吐旧值；②`np.clip(d_used, prev±max_step)` 对「变远」也限幅（max_step=1.0+1.2·v·DT≈1.64 m/帧@10 m/s ≈ 33 m/s），"
              "测到 seg13 854.4→854.9 以恒定 +1.64 m/帧爬升 1.7 s 才追回视觉值。建议：前车丢失 >0.5 s 复位滤波/限幅；"
              "限幅改非对称（只限「变近」或按同一目标连续性门控）；|d_fus−d_vis| 超阈值时直接吸附视觉。",
   "status": "pending"},
  {"content": "【待办·低】把「融合 dRel 与视觉背离」纳入回归：断言 |d_fus−d_vis|>5 m 的帧占比 <2%（当前 10.5%），"
              "并区分「合法 idx 过门采纳」与「滤波伪影」。",
   "status": "pending"},
]
items.extend(new)
d["updatedAt"] = int(time.time() * 1000)
json.dump(d, open(P, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("todos:", len(items))
for it in items:
    print(f"  [{it['status']:>11s}] {it['content'][:60]}")
