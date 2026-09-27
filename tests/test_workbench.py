"""工作台页面测试：四阶段、隔离视图、证据核对、演示时间线。"""

import unittest
from datetime import date

from src.workbench import render, run_demo_timeline
from src.seed import build


def demo_page(actor_id: str, page_date: date = date(2026, 11, 15)):
    wb = build()
    timeline = run_demo_timeline(wb)
    if actor_id == "ORG-1":
        notices = timeline
    else:
        notices = ["当前为受限视图：仅显示本企业资料或明确授权给本方的资料，其他企业资料不可见。"]
    return wb, render(wb, wb.actors[actor_id], page_date, notices)


class WorkbenchPageTest(unittest.TestCase):
    def test_four_stage_columns_present(self):
        _, page = demo_page("ORG-1")
        for label in ("初步接洽", "正式申报", "获批上市", "实际使用"):
            self.assertIn(label, page)

    def test_country_paths_and_sources_rendered(self):
        _, page = demo_page("ORG-1")
        for country in ("泰国", "越南", "印度尼西亚", "马来西亚"):
            self.assertIn(country, page)
        self.assertIn("98/2021/ND-CP", page)
        self.assertIn("Regalkes", page)
        self.assertIn("泰文", page)
        self.assertIn("Act 737", page)

    def test_tasks_show_assignee_and_deadline(self):
        _, page = demo_page("ORG-1")
        self.assertIn("李注册（企业RA）", page)
        self.assertIn("2026-10-18", page)
        self.assertIn("驳回整改", page)

    def test_change_impacts_rendered_with_generated_tasks(self):
        wb, page = demo_page("ORG-1")
        for label in ("证书到期", "适应症调整", "生产场地变化", "代理终止"):
            self.assertIn(label, page)
        # 每类变更都应至少生成一个带责任人与期限的任务
        event_tasks = [
            t
            for t in wb.tasks.values()
            if t.source_event_id is not None
        ]
        self.assertGreaterEqual(len(event_tasks), 4)

    def test_evidence_decision_table_freezes_versions(self):
        _, page = demo_page("ORG-1")
        self.assertIn("符合越南 C 类器械准入条件", page)
        self.assertIn("VER-202", page)

    def test_old_partner_cannot_see_other_companies(self):
        _, page = demo_page("P-OLD")
        self.assertNotIn("邻省医械", page)
        self.assertNotIn("某企业自持产品", page)
        # 只被授权了 CFS 一份资料
        self.assertIn("自由销售证书", page)
        self.assertNotIn("多中心临床试验报告", page)
        # 没有代理关系 → 看不到任何申请卡片
        self.assertNotIn("VasoNav", page)

    def test_other_enterprise_isolated(self):
        wb, page = demo_page("ENT-2")
        self.assertNotIn("自由销售证书", page)
        self.assertNotIn("VasoNav", page)
        # 只能看到本企业的资料条目
        self.assertIn("邻省企业自有证书", page)
        self.assertNotIn("多中心临床试验报告", page)
        # 看板上不应出现任何申请列内容
        self.assertEqual(wb.visible_applications(wb.actors["ENT-2"]), [])

    def test_agent_termination_removes_agent_from_thai_card(self):
        wb, page = demo_page("ORG-1")
        self.assertIn("未指定（授权链中断）", page)
        self.assertIsNone(wb.paths["PATH-TH"].agent_id)

    def test_stale_filing_blocked_notice(self):
        _, page = demo_page("ORG-1")
        self.assertIn("旧版/跨范围申报已被拦截", page)
        self.assertIn("旧版资料不得申报", page)


if __name__ == "__main__":
    unittest.main()
