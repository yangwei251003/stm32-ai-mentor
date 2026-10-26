# V3 竞赛侧车工作流

V3 是独立的竞赛账本：每项竞赛存放在 `Competitions/<competition_id>/`，含 `events.jsonl` 和派生的 `snapshot.json`。它与 V1 学习账本、V2 项目账本共享的仅是不可变 ID 或证据引用，**不做跨账本双写**。

## Intake 与规则冻结

先记录 `CompetitionIntake`：赛事、适配器（`nuedc`、`cpipc`、`soc_china` 或 `generic`）、届次、队伍、截止期和约束。随后记录 `RuleSet`，包括官方 URL、来源层级、检索日、规则摘要的 SHA-256 和 AI/匿名政策。不要复制受版权保护的完整规则原文。

来源层级依次是 `official`、`organizer_authorized`、`archived_official`、`secondary`。官方事实优先；无法访问或仅有旧届时记录 `availability: "unreachable"` 和降级来源，只能用于草稿风险提示。规则在检索日后 **7 天** 失鲜；提交预检要求新鲜的 `official` RuleSet。规则哈希更新会使旧 `Deliverable` 失效，需复核后重建。

## 证据、诚信与完整草稿

`Citation` 保存前案、技术事实或规则的链接、层级、检索日和用途；创新主张至少应关联 `prior_art`。`AIUse` 记录工具、用途与是否按规则披露。`Deliverable` 保存规则哈希、引用和按主张分类的证据 ID；可以制作有完整证据链的 `draft_complete` 草稿，但不得把推断、模板或未经验证的描述写成实测/创新结果。

提交预检检查：来源和新鲜度、规则更新、匿名、AI 使用披露/禁止、引用、前案、创新实验、实测证据、未知证据和伪造声明。被标记为 `invalidated` 的材料不可提交。提交本身不自动发生：只可通过 `reported_by_user` 加有效回执记录 `competition.submission_reported`。

## CLI

```powershell
python .agents/skills/stm32-ai-mentor/scripts/competition_tool.py --competitions-dir Competitions init --competition-id demo --intake '{...}' --idempotency-key intake-demo
python .agents/skills/stm32-ai-mentor/scripts/competition_tool.py --competitions-dir Competitions record --competition-id demo --event-type competition.rules_frozen --payload '{...}' --expected-revision 1 --idempotency-key rules-v1
python .agents/skills/stm32-ai-mentor/scripts/competition_tool.py --competitions-dir Competitions preflight --competition-id demo --deliverable-id report
```

每次写入均需 `expected_revision` 和幂等键；脚本以锁、追加事件、原子快照和重建比对保护账本。快照或事件不一致时 fail-closed，先人工核查，不覆盖。
