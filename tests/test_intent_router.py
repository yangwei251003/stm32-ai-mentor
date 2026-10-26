import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "scripts" / "intent_router.py"


def route(intent: str) -> dict:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--intent", intent],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_v3_competition_intent_wins_when_full_project_generation_is_also_requested():
    result = route("我要参加电赛，请直接生成完整 STM32 工程、论文和答辩材料")

    assert result["route"] == "V3"
    assert result["workflow"] == "competition"
    assert 1 <= len(result["questions"]) <= 3


def test_v2_generation_intent_wins_over_v1_learning_words():
    result = route("边学边帮我生成可交付的完整智能车工程、BOM、接线和固件")

    assert result["route"] == "V2"
    assert result["workflow"] == "project_generation"
    assert 1 <= len(result["questions"]) <= 3


def test_ordinary_v1_route_is_compact_and_does_not_market_sidecars():
    result = route("继续上一节 GPIO 课堂，先检查作业和准备度")

    assert result == {"route": "V1", "workflow": "classroom", "questions": []}
    rendered = json.dumps(result, ensure_ascii=False)
    for marketing_term in ("升级", "更强", "专业版", "推荐 V2", "推荐 V3"):
        assert marketing_term not in rendered


def test_router_never_asks_more_than_three_questions():
    for intent in (
        "生成一个完整项目",
        "参加全国大学生电子设计竞赛并完成作品",
        "解释 GPIO 上拉输入",
    ):
        assert len(route(intent)["questions"]) <= 3


@pytest.mark.parametrize(
    "intent",
    [
        "我要做一辆智能车",
        "我想做一个自动浇水花盆",
        "帮我做个桌面温湿度监测站",
        "给我搭建一套家庭环境面板",
        "我打算开发一个低压门窗报警器",
        "想实现一台简易数据采集仪",
    ],
)
def test_natural_build_requests_route_to_v2(intent):
    assert route(intent)["route"] == "V2"


@pytest.mark.parametrize(
    "intent",
    [
        "教我智能车怎么做",
        "比赛用定时器怎么实现",
    ],
)
def test_learning_questions_without_delivery_or_participation_stay_in_v1(intent):
    assert route(intent) == {"route": "V1", "workflow": "classroom", "questions": []}
