#!/usr/bin/env python3
"""Deterministic intent router for the V1/V2/V3 STM32 workflows."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")


V3_PARTICIPATION_MARKERS = (
    "参加竞赛",
    "参加比赛",
    "参加电赛",
    "参赛",
    "备赛",
    "报名竞赛",
    "报名比赛",
)
V3_CONTEXT_MARKERS = ("竞赛", "比赛", "电赛", "挑战杯", "创新创业", "competition")
V3_DELIVERY_MARKERS = (
    "作品",
    "提交",
    "交付",
    "论文",
    "答辩",
    "选题",
    "创新点",
    "规则",
    "截止",
)
V2_MARKERS = (
    "完整工程",
    "完整项目",
    "生成项目",
    "生成一个",
    "一键生成",
    "可交付",
    "交付工程",
    "项目生成",
    "project builder",
)
LEARNING_MARKERS = ("教我", "怎么学", "讲解", "解释", "课堂", "练习", "带我学", "一步一步学")
BUILD_OBJECT_MARKERS = (
    "智能车",
    "项目",
    "系统",
    "装置",
    "机器人",
    "控制器",
    "检测器",
    "监测",
    "报警器",
    "花盆",
    "台灯",
    "风扇",
    "面板",
    "采集仪",
    "气象站",
)


def route_intent(intent: str) -> dict[str, Any]:
    normalized = intent.strip().lower()
    competition_context = any(marker in normalized for marker in V3_CONTEXT_MARKERS)
    explicit_competition = any(marker in normalized for marker in V3_PARTICIPATION_MARKERS) or (
        competition_context and any(marker in normalized for marker in V3_DELIVERY_MARKERS)
    )
    if explicit_competition:
        return {
            "route": "V3",
            "workflow": "competition",
            "questions": [
                "具体竞赛、赛道和官方规则来源是什么？",
                "截止时间与当前所处阶段是什么？",
                "队伍能力、已有方案和可核查证据有哪些？",
            ],
        }
    if any(marker in normalized for marker in V2_MARKERS):
        return {
            "route": "V2",
            "workflow": "project_generation",
            "questions": [
                "目标功能、可观察验收结果和明确不做的范围是什么？",
                "MCU、封装、板卡版本和工具链基线是什么？",
                "已有器件、预算、时间与安全约束是什么？",
            ],
        }
    if not any(marker in normalized for marker in LEARNING_MARKERS):
        natural_build = re.search(
            r"(?:我要|我想|帮我|给我|我打算|打算|想)(?:做|制作|搭建|实现|开发)",
            normalized,
        )
        if natural_build and any(marker in normalized for marker in BUILD_OBJECT_MARKERS):
            return {
                "route": "V2",
                "workflow": "project_generation",
                "questions": [
                    "目标功能、可观察验收结果和明确不做的范围是什么？",
                    "MCU、封装、板卡版本和工具链基线是什么？",
                    "已有器件、预算、时间与安全约束是什么？",
                ],
            }
    return {"route": "V1", "workflow": "classroom", "questions": []}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="STM32 AI Mentor intent router")
    parser.add_argument("--intent", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(route_intent(args.intent), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
