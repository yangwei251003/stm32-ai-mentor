from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".agents" / "skills" / "stm32-ai-mentor"
PROTOCOL = SKILL / "references" / "pedagogy" / "classroom-recovery-and-hardware-modes.md"


def test_classroom_has_three_hardware_routes_and_bom_priorities():
    text = PROTOCOL.read_text(encoding="utf-8")
    for term in (
        "实机路线", "部分器件路线", "无实板路线",
        "本课必需", "可替代", "可延期", "停止点", "不得升级为 V5",
    ):
        assert term in text


def test_board_identification_and_build_failure_intake_are_actionable():
    text = PROTOCOL.read_text(encoding="utf-8")
    for term in (
        "MCU 丝印", "封装", "板卡版本", "晶振", "USB 上拉", "板载 LED",
        "供电路径", "SWD", "IDE 版本", "CubeMX 版本", "第一条未截断错误",
        "完整命令", "blocked", "下一条诊断问题",
    ):
        assert term in text


def test_compressed_prestudy_keeps_non_skippable_learning_gates():
    text = PROTOCOL.read_text(encoding="utf-8")
    assert "压缩预习" in text
    assert "恰好 5 题" in text
    assert "4/5" in text
    assert "安全题" in text
    assert "不可跳过" in text
    skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    assert "classroom-recovery-and-hardware-modes.md" in skill_text

