"""服务层行为测试：隔离、版本拦截、任务责任、变更影响、阶段流转。"""

import unittest
from datetime import date

from src.models import (
    ChangeEvent,
    ChangeKind,
    EvidenceVersion,
    Stage,
    TaskKind,
    TaskStatus,
    VersionStatus,
)
from src.seed import TODAY, build
from src.services import FilingError


class IsolationTest(unittest.TestCase):
    def setUp(self):
        self.wb = build()

    def test_enterprise_sees_only_own_items(self):
        company = self.wb.actors["ENT-1"]
        other = self.wb.actors["ENT-2"]
        own_ids = {i.item_id for i in self.wb.visible_items(company)}
        other_ids = {i.item_id for i in self.wb.visible_items(other)}
        self.assertIn("EV-CERT-SEA", own_ids)
        self.assertEqual(other_ids, {"EV-OTHER"})
        self.assertNotIn("EV-CERT-SEA", other_ids)

    def test_enterprise_sees_only_own_applications(self):
        other = self.wb.actors["ENT-2"]
        self.assertEqual(self.wb.visible_applications(other), [])

    def test_partner_sees_only_shared_items_and_no_applications(self):
        partner = self.wb.actors["P-OLD"]
        ids = {i.item_id for i in self.wb.visible_items(partner)}
        self.assertEqual(ids, {"EV-CERT-SEA"})
        self.assertEqual(self.wb.visible_applications(partner), [])

    def test_agent_sees_application_on_own_path(self):
        agent = self.wb.actors["P-TH"]
        apps = self.wb.visible_applications(agent)
        self.assertEqual([a.application_id for a in apps], ["APP-TH"])

    def test_service_org_sees_everything(self):
        admin = self.wb.actors["ORG-1"]
        self.assertEqual(len(self.wb.visible_applications(admin)), 4)
        self.assertEqual(len(self.wb.visible_items(admin)), len(self.wb.items))


class FilingVersionTest(unittest.TestCase):
    def setUp(self):
        self.wb = build()

    def test_stale_version_rejected(self):
        with self.assertRaises(FilingError) as ctx:
            self.wb.submit_filing(
                "APP-ID",
                ("VER-101", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601"),
                TODAY,
                by="旧合作方",
            )
        self.assertTrue(any("旧版资料不得申报" in p for p in ctx.exception.problems))

    def test_out_of_scope_item_rejected(self):
        # 泰越互认证书（VER-102）适用范围不含印尼
        with self.assertRaises(FilingError) as ctx:
            self.wb.submit_filing(
                "APP-ID",
                ("VER-102", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601"),
                TODAY,
                by="企业RA",
            )
        self.assertTrue(any("适用范围不含印度尼西亚" in p for p in ctx.exception.problems))

    def test_missing_required_kind_rejected(self):
        # 印尼路径要求集采机会资料，缺 EV-PROC-ID
        with self.assertRaises(FilingError) as ctx:
            self.wb.submit_filing(
                "APP-ID",
                ("VER-111", "VER-202", "VER-303", "VER-402", "VER-501"),
                TODAY,
                by="企业RA",
            )
        self.assertTrue(any("集采机会" in p for p in ctx.exception.problems))

    def test_other_enterprise_item_rejected(self):
        with self.assertRaises(FilingError) as ctx:
            self.wb.submit_filing(
                "APP-ID",
                ("VER-901", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601"),
                TODAY,
                by="企业RA",
            )
        self.assertTrue(any("属于其他企业" in p for p in ctx.exception.problems))

    def test_valid_package_advances_to_formal_submission(self):
        self.wb.submit_filing(
            "APP-ID",
            ("VER-111", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601"),
            TODAY,
            by="企业RA",
        )
        app = self.wb.applications["APP-ID"]
        self.assertIs(app.stage, Stage.FORMAL_SUBMISSION)
        self.assertEqual(app.filed_on, TODAY)
        self.assertEqual(len(app.filed_package), 6)

    def test_failed_filing_is_audited(self):
        with self.assertRaises(FilingError):
            self.wb.submit_filing("APP-ID", ("VER-101",), TODAY, by="旧合作方")
        actions = [e.action for e in self.wb.audit]
        self.assertIn("申报拦截", actions)


class TaskTest(unittest.TestCase):
    def setUp(self):
        self.wb = build()

    def test_supplement_and_rejection_have_owner_and_due(self):
        tasks = self.wb.open_tasks("APP-TH")
        self.assertEqual(len(tasks), 2)
        kinds = {t.kind for t in tasks}
        self.assertEqual(kinds, {TaskKind.SUPPLEMENT, TaskKind.REJECTION})
        for task in tasks:
            self.assertEqual(task.assignee, "李注册（企业RA）")
            self.assertGreater(task.due_on, TODAY)

    def test_overdue_detection(self):
        task = self.wb.request_supplement(
            "APP-TH", "补交历史记录", date(2026, 9, 1), date(2026, 8, 20), "审评员"
        )
        overdue = self.wb.overdue_tasks(TODAY)
        self.assertIn(task, overdue)
        self.wb.complete_task(task.task_id, TODAY, "李注册")
        self.assertNotIn(task, self.wb.overdue_tasks(TODAY))
        self.assertIs(task.status, TaskStatus.DONE)

    def test_rejection_blocks_approval_until_resolved(self):
        with self.assertRaises(FilingError):
            self.wb.approve("APP-TH", "评审组", TODAY)
        rejection = next(
            t for t in self.wb.open_tasks("APP-TH") if t.kind is TaskKind.REJECTION
        )
        self.wb.complete_task(rejection.task_id, TODAY, "李注册")
        self.assertFalse(self.wb.applications["APP-TH"].has_rejection)
        self.wb.approve("APP-TH", "评审组", TODAY)
        self.assertIs(self.wb.applications["APP-TH"].stage, Stage.APPROVED)


class ImpactTest(unittest.TestCase):
    def setUp(self):
        self.wb = build()

    def test_certificate_expiry_marks_version_and_creates_renewal(self):
        self.wb.submit_filing(
            "APP-ID",
            ("VER-111", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601"),
            TODAY,
            by="企业RA",
        )
        report = self.wb.apply_change(
            ChangeEvent(
                kind=ChangeKind.CERTIFICATE_EXPIRED,
                occurred_on=date(2026, 10, 21),
                note="印尼注册证书到期",
                item_id="EV-CERT-ID",
            )
        )
        # 印尼申请已正式申报 → 受影响；泰国/越南用的是另一张证书 → 不受影响
        self.assertEqual([i.application_id for i in report.impacts], ["APP-ID"])
        version = self.wb.get_version("VER-111")
        self.assertIs(version.status, VersionStatus.EXPIRED)
        task = self.wb.tasks[report.impacts[0].task_id]
        self.assertIs(task.kind, TaskKind.RENEWAL)
        self.assertEqual(task.assignee, "陈项目经理（服务机构）")

    def test_certificate_expiry_skips_initial_contact(self):
        # 印尼尚在初步接洽，未递交 → 直接换新证即可，不算受影响申请
        report = self.wb.apply_change(
            ChangeEvent(
                kind=ChangeKind.CERTIFICATE_EXPIRED,
                occurred_on=date(2026, 10, 21),
                note="印尼注册证书到期",
                item_id="EV-CERT-ID",
            )
        )
        self.assertEqual(report.impacts, [])

    def test_indication_change_hits_all_filed_paths(self):
        self.wb.submit_filing(
            "APP-ID",
            ("VER-111", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601"),
            TODAY,
            by="企业RA",
        )
        report = self.wb.apply_change(
            ChangeEvent(
                kind=ChangeKind.INDICATION_ADJUSTED,
                occurred_on=TODAY,
                note="适应症扩展至冠脉血管介入导航",
                product_id="P1",
            )
        )
        affected = {i.application_id for i in report.impacts}
        self.assertEqual(affected, {"APP-TH", "APP-VN", "APP-ID", "APP-MY"})
        self.assertEqual(
            self.wb.products["P1"].indication, "适应症扩展至冠脉血管介入导航"
        )

    def test_site_change_updates_product_and_tasks(self):
        report = self.wb.apply_change(
            ChangeEvent(
                kind=ChangeKind.SITE_CHANGED,
                occurred_on=TODAY,
                note="迁至南宁二号场地",
                product_id="P1",
            )
        )
        self.assertEqual(self.wb.products["P1"].production_site, "迁至南宁二号场地")
        # 已申报的泰国、已获批的越南和马来西亚受影响；初步接洽的印尼不算
        self.assertEqual(
            {i.application_id for i in report.impacts}, {"APP-TH", "APP-VN", "APP-MY"}
        )

    def test_agent_termination_clears_path_and_flags_application(self):
        report = self.wb.apply_change(
            ChangeEvent(
                kind=ChangeKind.AGENT_TERMINATED,
                occurred_on=TODAY,
                note="曼谷代理终止合作",
                agent_id="P-TH",
            )
        )
        self.assertEqual([i.application_id for i in report.impacts], ["APP-TH"])
        self.assertIsNone(self.wb.paths["PATH-TH"].agent_id)
        # 代理终止后该合作方不再能看到泰国申请
        agent = self.wb.actors["P-TH"]
        self.assertEqual(self.wb.visible_applications(agent), [])


class StageFlowTest(unittest.TestCase):
    def setUp(self):
        self.wb = build()

    def test_next_actions_cover_every_stage(self):
        for app in self.wb.applications.values():
            actions = self.wb.next_actions(app, TODAY)
            self.assertTrue(actions, f"{app.application_id} 缺少下一步行动")

    def test_initial_contact_actions_list_gaps(self):
        # 种子数据下印尼六类资料齐备、代理已指定 → 提示可申报
        actions = self.wb.next_actions(self.wb.applications["APP-ID"], TODAY)
        self.assertIn("资料齐备，可按现行版本正式提交申报", actions)

        # 缺少集采机会资料时应明确提示补充
        del self.wb.items["EV-PROC-ID"]
        actions = self.wb.next_actions(self.wb.applications["APP-ID"], TODAY)
        self.assertTrue(any("集采机会" in a for a in actions))

    def test_cannot_use_before_approval(self):
        with self.assertRaises(FilingError):
            self.wb.start_use("APP-TH", "评审组", TODAY)
        self.wb.start_use("APP-VN", "评审组", TODAY)
        self.assertIs(self.wb.applications["APP-VN"].stage, Stage.IN_USE)

    def test_grouped_by_stage(self):
        grouped = self.wb.applications_by_stage()
        self.assertEqual(
            [a.application_id for a in grouped[Stage.INITIAL_CONTACT]], ["APP-ID"]
        )
        self.assertEqual(
            [a.application_id for a in grouped[Stage.FORMAL_SUBMISSION]], ["APP-TH"]
        )
        self.assertEqual(
            {a.application_id for a in grouped[Stage.APPROVED]}, {"APP-VN", "APP-MY"}
        )


class DecisionAuditTest(unittest.TestCase):
    def setUp(self):
        self.wb = build()

    def test_decision_freezes_evidence_versions(self):
        decision = self.wb.decisions[0]
        self.assertEqual(decision.application_id, "APP-VN")
        refs = dict(decision.evidence_refs)
        self.assertEqual(refs["EV-TRIAL"], "VER-202")
        self.assertEqual(refs["EV-CERT-SEA"], "VER-102")

    def test_decision_rejects_stale_reference(self):
        with self.assertRaises(FilingError):
            self.wb.record_decision(
                "APP-TH",
                "准予补件后复审",
                "评审组",
                TODAY,
                evidence_refs=(("EV-CERT-SEA", "VER-101"),),
            )

    def test_filed_evidence_marks_superseded(self):
        app = self.wb.applications["APP-VN"]
        rows = self.wb.filed_evidence(app, TODAY)
        by_item = {item.item_id: still for item, _, still in rows}
        self.assertTrue(by_item["EV-TRIAL"])  # v2 仍现行
        # 模拟试验报告出第 3 版后，申报包里的 v2 应显示为已更新
        self.wb.versions["EV-TRIAL"].append(
            EvidenceVersion("VER-203", "EV-TRIAL", 3, TODAY, "36 个月随访版")
        )
        rows = self.wb.filed_evidence(app, TODAY)
        by_item = {item.item_id: still for item, _, still in rows}
        self.assertFalse(by_item["EV-TRIAL"])


if __name__ == "__main__":
    unittest.main()
