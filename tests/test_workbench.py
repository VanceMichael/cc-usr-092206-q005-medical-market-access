"""统一准入工作台服务测试。

覆盖：资料隔离、补件/驳回期限、四类变更影响、旧版申报识别、
证据版本稽核、四阶段视图与下一步行动、页面不泄密。
"""

import json
import unittest
from pathlib import Path

from src.domain import load_workbench
from src.page import render_workbench_html
from src.workbench import (
    STAGE_ORDER,
    all_impacts,
    application_card,
    build_index,
    current_version,
    decision_audit,
    event_impact,
    expiring_artifacts,
    next_actions,
    open_actions,
    stale_filings,
    visible_applications,
    visible_artifacts,
    workbench_view,
)

DATA_PATH = Path("fixtures/domain.json")
AS_OF = "2026-09-27"


class WorkbenchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = load_workbench(DATA_PATH)
        cls.idx = build_index(cls.data)

    # ---------- 加载与校验 ----------

    def test_fixture_loads_with_indexes(self):
        self.assertEqual({c["id"] for c in self.data["countries"]}, {"TH", "VN", "ID"})
        self.assertEqual(len(self.data["paths"]), 5)

    def _rejects(self, mutate):
        broken = json.loads(json.dumps(self.data))
        mutate(broken)
        path = Path("/tmp/broken-domain.json")
        path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ValueError):
            load_workbench(path)

    def test_rejects_unknown_pinned_version(self):
        def mutate(d):
            d["applications"][0]["dossier"][0]["version"] = "v99"
        self._rejects(mutate)

    def test_rejects_path_country_mismatch(self):
        def mutate(d):
            d["applications"][0]["path"] = "path-ctffr-vn"
        self._rejects(mutate)

    def test_rejects_event_without_subject(self):
        def mutate(d):
            d["events"][0].pop("product")
        self._rejects(mutate)

    # ---------- 授权隔离 ----------

    def test_service_org_sees_everything(self):
        apps = visible_applications(self.data, "org-gx")
        self.assertEqual(len(apps), 5)
        self.assertEqual(len(visible_artifacts(self.data, "org-gx")), len(self.data["artifacts"]))

    def test_enterprise_sees_only_own_applications(self):
        apps = visible_applications(self.data, "org-b")
        self.assertEqual([a["id"] for a in apps], ["app-peer-vn"])

    def test_enterprise_cannot_see_other_company_materials(self):
        # 同行企业看不到 A 企业的证书、临床、标签、医院合作资料
        titles = " ".join(a["title"] for a in visible_artifacts(self.data, "org-b"))
        self.assertNotIn("CT-FFR", titles)
        self.assertNotIn("冠脉", titles)
        self.assertNotIn("泰文标签", titles)

    def test_partner_only_sees_granted_artifact(self):
        arts = visible_artifacts(self.data, "org-partner")
        self.assertEqual([a["id"] for a in arts], ["art-clin-ctffr"])
        self.assertEqual(visible_applications(self.data, "org-partner"), [])

    def test_revoked_grant_removes_visibility(self):
        data = json.loads(json.dumps(self.data))
        for grant in data["authorizations"]:
            if grant["org"] == "org-partner":
                grant["status"] = "revoked"
        self.assertEqual(visible_artifacts(data, "org-partner"), [])

    def test_agent_sees_only_agented_application(self):
        apps = visible_applications(self.data, "org-agent-id")
        self.assertEqual([a["id"] for a in apps], ["app-ctffr-id"])
        # 越南、泰国的申请不可见
        self.assertNotIn("app-ctffr-th", [a["id"] for a in apps])

    # ---------- 补件 / 驳回 ----------

    def test_open_actions_carry_owner_and_deadline(self):
        rows = open_actions(self.data, "org-gx", AS_OF)
        by_id = {a["id"]: a for a in rows}
        self.assertNotIn("act-003", by_id)  # 已办结不出现
        rejected = by_id["act-002"]
        self.assertTrue(rejected["overdue"])
        self.assertEqual(rejected["days_left"], -7)
        self.assertEqual(rejected["owner"]["person"], "黄老师（法规顾问）")
        self.assertEqual(rejected["owner_org_name"], "广西面向东盟药械准入服务中心")
        supplement = by_id["act-001"]
        self.assertFalse(supplement["overdue"])
        self.assertEqual(supplement["days_left"], 12)
        # 按到期日升序，逾期事项排最前
        self.assertEqual(rows[0]["id"], "act-002")

    def test_actions_respect_visibility(self):
        ids = {a["id"] for a in open_actions(self.data, "org-agent-id", AS_OF)}
        self.assertEqual(ids, {"act-005"})

    # ---------- 四类变更影响 ----------

    def _impact(self, event_id):
        event = next(e for e in self.data["events"] if e["id"] == event_id)
        return event_impact(self.data, event, AS_OF)

    def test_certificate_expiry_finds_dossier_applications(self):
        impact = self._impact("evt-cfs-expiry")
        apps = {a["application"]: a for a in impact["affected"]}
        self.assertEqual(set(apps), {"app-ctffr-th", "app-ctffr-id"})
        self.assertIn("2026-11-30", apps["app-ctffr-th"]["reasons"][0])
        self.assertIn("剩余 64 天", apps["app-ctffr-th"]["reasons"][0])

    def test_expired_certificate_is_flagged(self):
        impact = event_impact(
            self.data,
            next(e for e in self.data["events"] if e["id"] == "evt-cfs-expiry"),
            "2026-12-15",
        )
        reason = impact["affected"][0]["reasons"][0]
        self.assertIn("已过期", reason)

    def test_indication_change_hits_every_country_path(self):
        impact = self._impact("evt-indication")
        apps = {a["application"]: a["reasons"][0] for a in impact["affected"]}
        self.assertEqual(set(apps), {"app-ctffr-th", "app-ctffr-vn", "app-ctffr-id"})
        self.assertIn("变更注册", apps["app-ctffr-id"])
        self.assertIn("补充新适应症资料", apps["app-ctffr-th"])
        self.assertIn("申报策略", apps["app-ctffr-vn"])

    def test_site_change_hits_in_use_application(self):
        impact = self._impact("evt-site-change")
        apps = {a["application"]: a["reasons"][0] for a in impact["affected"]}
        self.assertEqual(set(apps), {"app-ecg-th"})
        self.assertIn("许可事项变更", apps["app-ecg-th"])

    def test_agent_termination_hits_application_and_procurement(self):
        impact = self._impact("evt-agent-end")
        apps = {a["application"]: a["reasons"][0] for a in impact["affected"]}
        self.assertEqual(set(apps), {"app-ctffr-id"})
        self.assertIn("30 日内指定新代理", apps["app-ctffr-id"])
        notes = " ".join(impact["notes"])
        self.assertIn("授权已收回", notes)
        self.assertIn("e-Katalog", notes)

    def test_impacts_filtered_for_agent(self):
        impacts = all_impacts(self.data, "org-agent-vn", AS_OF)
        types = {i["event"]["id"] for i in impacts}
        self.assertIn("evt-indication", types)
        self.assertNotIn("evt-site-change", types)
        self.assertNotIn("evt-agent-end", types)

    # ---------- 旧版申报识别 ----------

    def test_stale_filings_detect_outdated_dossier(self):
        rows = stale_filings(self.data, "org-gx", AS_OF)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["application"], "app-ctffr-vn")
        self.assertEqual(row["artifact"], "art-clin-ctffr")
        self.assertEqual(row["pinned"], "v1")
        self.assertEqual(row["current"], "v2")

    def test_approved_application_not_flagged_as_stale_filing(self):
        # 获批卷宗保留批准时的版本属于正常，旧版风险只提示接洽/申报阶段
        rows = stale_filings(self.data, "org-gx", AS_OF)
        self.assertNotIn("app-ctffr-id", [r["application"] for r in rows])

    # ---------- 证据版本稽核 ----------

    def test_decision_audit_statuses(self):
        rows = {r["decision"]: r for r in decision_audit(self.data, "org-gx", AS_OF)}
        self.assertEqual(rows["dec-001"]["worst"], "ok")
        self.assertEqual(rows["dec-002"]["worst"], "superseded")
        self.assertEqual(rows["dec-005"]["worst"], "stale_at_decision")
        self.assertEqual(rows["dec-003"]["worst"], "superseded")
        self.assertEqual(rows["dec-004"]["worst"], "ok")
        # 合作方误用 v1 的判断可被管理者核对到
        evidence = {e["artifact"]: e for e in rows["dec-005"]["evidence"]}
        self.assertEqual(evidence["art-clin-ctffr"]["status"], "stale_at_decision")

    def test_audit_hidden_from_other_enterprise(self):
        rows = decision_audit(self.data, "org-b", AS_OF)
        self.assertTrue(all(r["application"] == "app-peer-vn" for r in rows))

    # ---------- 四阶段视图与下一步 ----------

    def test_workbench_stages_partition_applications(self):
        view = workbench_view(self.data, "org-gx", AS_OF)
        counts = {s["id"]: len(s["applications"]) for s in view["stages"]}
        self.assertEqual(counts, {"lead": 1, "filing": 2, "approved": 1, "in_use": 1})
        self.assertEqual([s["id"] for s in view["stages"]], list(STAGE_ORDER))

    def test_card_pins_regulations_and_language(self):
        view = workbench_view(self.data, "org-gx", AS_OF)
        card = next(
            c for s in view["stages"] for c in s["applications"] if c["id"] == "app-ctffr-th"
        )
        citations = " ".join(r["citation"] for r in card["path"]["regulations"])
        self.assertIn("Medical Device Act", citations)
        self.assertEqual(card["label_language"], "泰文")
        self.assertIn("曼谷示例医疗注册代理", card["agent"])

    def test_next_actions_for_approved_product(self):
        app = self.idx["applications"]["app-ctffr-id"]
        card = workbench_view(self.data, "org-gx", AS_OF)
        flat = next(
            c for s in card["stages"] for c in s["applications"] if c["id"] == "app-ctffr-id"
        )
        texts = " ".join(a["text"] for a in flat["next_actions"])
        self.assertIn("代理终止", texts)
        self.assertIn("适应症", texts)
        self.assertIn("年度监测报告", texts)
        # 完整行动列表（未截断）应包含集采机会提示
        full = " ".join(a["text"] for a in next_actions(self.data, app, AS_OF))
        self.assertIn("e-Katalog", full)  # 获批产品才提示集采

    def test_lead_application_next_action_is_to_file(self):
        app = self.idx["applications"]["app-ctffr-vn"]
        card = application_card(self.data, app, AS_OF)
        # 旧版临床报告是首要行动之一
        self.assertTrue(any("v1" in a["text"] and "v2" in a["text"] for a in card["next_actions"]))

    # ---------- 到期提醒 ----------

    def test_expiring_window(self):
        rows = expiring_artifacts(self.data, "org-gx", AS_OF)
        titles = {r["artifact"]: r for r in rows}
        self.assertIn("art-cfs", titles)
        self.assertIn("art-hosp-bkk", titles)
        self.assertIn("art-proc-th", titles)
        self.assertNotIn("art-proc-id", titles)  # 95 天后，超出 90 天窗口
        self.assertEqual(set(titles["art-cfs"]["affected_applications"]),
                         {"app-ctffr-th", "app-ctffr-id"})

    # ---------- 页面 ----------

    def test_html_contains_key_sections(self):
        view = workbench_view(self.data, "org-gx", AS_OF)
        html = render_workbench_html(view)
        for word in ("初步接洽", "正式申报", "获批上市", "实际使用",
                     "补件与驳回", "变更影响分析", "准入判断证据稽核",
                     "黄老师", "逾期 7 天", "Medical Device Act"):
            self.assertIn(word, html)

    def test_html_does_not_leak_across_enterprises(self):
        view = workbench_view(self.data, "org-b", AS_OF)
        html = render_workbench_html(view)
        self.assertNotIn("CT-FFR", html)
        self.assertNotIn("冠脉", html)
        self.assertNotIn("曼谷", html)
        self.assertIn("压力延长管", html)

    def test_current_version_picks_latest_issued(self):
        artifact = self.idx["artifacts"]["art-clin-ctffr"]
        self.assertEqual(current_version(artifact)["version"], "v2")


if __name__ == "__main__":
    unittest.main()
