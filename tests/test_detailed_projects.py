"""Structural guardrails for the V1 detailed classroom material.

These tests intentionally check teaching and safety promises, not electrical
claims. Hardware success still requires learner-provided evidence.
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
DETAIL = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "projects" / "detailed"
V2_DETAIL = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "projects" / "v2-detailed"
CURRICULUM = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "curriculum" / "S0-S7_knowledge_graph.md"
CONTRACT = ROOT / ".agents" / "skills" / "stm32-ai-mentor" / "references" / "prestudy-handbook" / "classroom_contract.md"


class DetailedProjectTests(unittest.TestCase):
    def test_all_fifteen_projects_exist_once(self):
        files = sorted(DETAIL.glob("P*.md"))
        self.assertEqual(15, len(files))
        self.assertEqual([f"P{i:02d}" for i in range(1, 16)], [p.stem[:3] for p in files])

    def test_v2_library_has_thirty_patterns(self):
        self.assertEqual(30, len(list(V2_DETAIL.glob("*.md"))))

    def test_each_project_has_full_classroom_loop(self):
        required = (
            "课前预习手册",
            "小测",
            "课中",
            "导入/复习",
            "理论",
            "动手",
            "验收",
            "BOM",
            "CubeMX",
            "HAL_",  # template neutral check completed below
            "提示阶梯",
            "调试树",
            "作业",
            "生活应用",
            "挑战",
            "复盘",
            "安全门",
        )
        for project in DETAIL.glob("P*.md"):
            text = project.read_text(encoding="utf-8")
            for item in required:
                if item == "HAL_":
                    self.assertIn("HAL_", text, project.name)
                else:
                    self.assertIn(item, text, f"{project.name} misses {item}")
            self.assertIn("4/5", text, project.name)
            self.assertIn("F103", text, project.name)

    def test_each_project_has_overridable_wiring_table(self):
        for project in DETAIL.glob("P*.md"):
            text = project.read_text(encoding="utf-8")
            self.assertIn("## 可覆写接线表", text, project.name)
            self.assertIn("| 功能 | MCU 信号/外设 | 默认建议或能力要求 | 必须确认事项 |", text, project.name)
            # A table must contain at least two actual connection/constraint rows.
            section = text.split("## 可覆写接线表", 1)[1].split("## ", 1)[0]
            self.assertGreaterEqual(section.count("\n|"), 3, project.name)

    def test_special_projects_carry_explicit_safety_boundaries(self):
        expectations = {
            "P10-rtc-logger.md": ("受控", "不能标功耗数值"),
            "P11-parking-servo.md": ("Echo", "不可作真实防撞"),
            "P12-smart-fan.md": ("驱动器", "不接市电"),
            "P13-can-node.md": ("120Ω", "不接汽车"),
            "P14-usb-cdc-instrument.md": ("回灌", "板级"),
            "P15-freertos-panel.md": ("20KB", "HardFault"),
        }
        for file_name, phrases in expectations.items():
            text = (DETAIL / file_name).read_text(encoding="utf-8")
            for phrase in phrases:
                self.assertIn(phrase, text, f"{file_name} misses safety cue {phrase}")

    def test_curriculum_has_s0_to_s7_and_evidence_policy(self):
        text = CURRICULUM.read_text(encoding="utf-8")
        for node in range(8):
            self.assertIn(f"S{node}", text)
        for phrase in ("必须记住", "重点理解", "会查", "常考", "常错", "预习 5 题", "来源", "验证"):
            self.assertIn(phrase, text)
        self.assertIn("无实板", text)

    def test_shared_contract_has_remediation_and_four_homeworks(self):
        text = CONTRACT.read_text(encoding="utf-8")
        for phrase in ("4/5", "微课", "兴趣导入", "必要理论", "分阶段动手", "验收与迁移", "必做", "生活应用", "选做挑战", "复盘"):
            self.assertIn(phrase, text)


if __name__ == "__main__":
    unittest.main()
