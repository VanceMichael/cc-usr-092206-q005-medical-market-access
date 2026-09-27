"""区域服务机构统一工作台的服务层。

职责：
- 按企业与授权关系隔离资料，未经授权的企业资料互不可见；
- 正式申报校验证据版本与适用范围，拦截旧版、跨用途资料；
- 补件、驳回、续期、变更任务一律落到责任人与期限；
- 证书到期、适应症调整、生产场地变化、代理终止自动定位受影响申请；
- 记录准入判断所采用的证据版本，供管理者核对。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .models import (
    AccessDecision,
    Actor,
    Application,
    ChangeEvent,
    ChangeKind,
    EvidenceItem,
    EvidenceKind,
    EvidenceVersion,
    Impact,
    ImpactReport,
    Product,
    RegistrationPath,
    Role,
    STAGE_ORDER,
    Stage,
    Task,
    TaskKind,
    TaskStatus,
    VersionStatus,
)

DEFAULT_RENEWAL_DAYS = 30
DEFAULT_VARIATION_DAYS = 45
RENEWAL_NOTICE_DAYS = 90


@dataclass
class AuditEntry:
    on: date
    actor: str
    action: str
    target: str
    detail: str = ""


class FilingError(ValueError):
    """申报包校验未通过，问题清单见 problems。"""

    def __init__(self, problems: list[str]):
        super().__init__("；".join(problems))
        self.problems = problems


class Workbench:
    def __init__(self) -> None:
        self.actors: dict[str, Actor] = {}
        self.products: dict[str, Product] = {}
        self.paths: dict[str, RegistrationPath] = {}
        self.items: dict[str, EvidenceItem] = {}
        self.versions: dict[str, list[EvidenceVersion]] = {}
        self.applications: dict[str, Application] = {}
        self.decisions: list[AccessDecision] = []
        self.tasks: dict[str, Task] = {}
        self.events: list[ChangeEvent] = []
        self.impacts: list[ImpactReport] = []
        self.audit: list[AuditEntry] = []
        self._seq = 0

    # ------------------------------------------------------------------ 基础

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}-{self._seq:03d}"

    def path_of(self, application: Application) -> RegistrationPath:
        return self.paths[application.path_id]

    def product_of(self, application: Application) -> Product:
        return self.products[self.paths[application.path_id].product_id]

    def log(self, on: date, actor: str, action: str, target: str, detail: str = "") -> None:
        self.audit.append(AuditEntry(on, actor, action, target, detail))

    # ------------------------------------------------------------------ 隔离

    def can_see_item(self, actor: Actor, item: EvidenceItem) -> bool:
        if actor.role is Role.SERVICE_ORG:
            return True
        if actor.enterprise_id and item.enterprise_id == actor.enterprise_id:
            return True
        return actor.actor_id in item.shared_with

    def can_see_application(self, actor: Actor, application: Application) -> bool:
        if actor.role is Role.SERVICE_ORG:
            return True
        if actor.enterprise_id == application.enterprise_id:
            return True
        # 合作方仅能看到自己担任本地代理的路径上的申请；
        # 资料授权（shared_with）只开放资料本身，不开放企业其他申请
        return self.path_of(application).agent_id == actor.actor_id

    def visible_applications(self, actor: Actor) -> list[Application]:
        return [a for a in self.applications.values() if self.can_see_application(actor, a)]

    def visible_items(self, actor: Actor) -> list[EvidenceItem]:
        return [i for i in self.items.values() if self.can_see_item(actor, i)]

    # ------------------------------------------------------------------ 版本

    def current_version(self, item_id: str, today: date) -> EvidenceVersion | None:
        """现行有效版本：状态为现行且未超过有效期。"""

        candidates = [
            v
            for v in self.versions.get(item_id, [])
            if v.status is VersionStatus.CURRENT
            and (v.valid_until is None or v.valid_until >= today)
        ]
        return max(candidates, key=lambda v: v.version_no, default=None)

    def get_version(self, version_id: str) -> EvidenceVersion:
        for versions in self.versions.values():
            for version in versions:
                if version.version_id == version_id:
                    return version
        raise KeyError(version_id)

    def filed_evidence(
        self, application: Application, today: date
    ) -> list[tuple[EvidenceItem, EvidenceVersion, bool]]:
        """返回申报包中每份 (资料, 版本, 目前是否仍现行)。"""

        rows: list[tuple[EvidenceItem, EvidenceVersion, bool]] = []
        current_ids = {
            v.version_id
            for item in self.items.values()
            if (v := self.current_version(item.item_id, today)) is not None
        }
        for version_id in application.filed_package:
            version = self.get_version(version_id)
            item = self.items[version.item_id]
            rows.append((item, version, version.version_id in current_ids))
        return rows

    # ---------------------------------------------------------- 申报与校验

    def filing_problems(
        self, application: Application, package: tuple[str, ...], today: date
    ) -> list[str]:
        path = self.path_of(application)
        problems: list[str] = []
        seen_items: set[str] = set()

        for version_id in package:
            try:
                version = self.get_version(version_id)
            except KeyError:
                problems.append(f"申报件 {version_id} 不存在")
                continue
            item = self.items.get(version.item_id)
            if item is None:
                problems.append(f"版本 {version_id} 对应的资料已删除")
                continue
            if item.enterprise_id != application.enterprise_id:
                problems.append(f"《{item.title}》属于其他企业，不得用于本申请")
                continue
            if not item.covers(path):
                problems.append(
                    f"《{item.title}》适用范围不含{path.country}，不能用于{path.country}申报"
                )
            current = self.current_version(item.item_id, today)
            if current is None:
                problems.append(f"《{item.title}》没有现行有效版本，需先更新")
            elif version.version_id != current.version_id:
                problems.append(
                    f"《{item.title}》拟用第{version.version_no}版，"
                    f"现行有效为第{current.version_no}版，旧版资料不得申报"
                )
            seen_items.add(item.item_id)

        kinds = {self.items[i].kind for i in seen_items if i in self.items}
        for kind in path.required_evidence:
            if kind not in kinds:
                problems.append(f"缺少{path.country}路径要求的资料类型：{kind.value}")
        if path.requires_local_agent and not path.agent_id:
            problems.append(f"{path.country}要求指定本地代理，当前尚未指定")
        return problems

    def submit_filing(
        self,
        application_id: str,
        package: tuple[str, ...],
        today: date,
        by: str,
    ) -> None:
        application = self.applications[application_id]
        problems = self.filing_problems(application, package, today)
        if problems:
            self.log(today, by, "申报拦截", application_id, "；".join(problems))
            raise FilingError(problems)
        application.stage = Stage.FORMAL_SUBMISSION
        application.filed_package = tuple(package)
        application.filed_on = today
        self.log(
            today,
            by,
            "正式申报",
            application_id,
            f"提交 {len(package)} 份现行证据：{', '.join(package)}",
        )

    # ---------------------------------------------------------- 任务与决定

    def _add_task(
        self,
        application: Application,
        kind: TaskKind,
        title: str,
        due_on: date,
        today: date,
        by: str,
        source_event_id: str | None = None,
    ) -> Task:
        task = Task(
            task_id=self._id("TASK"),
            application_id=application.application_id,
            kind=kind,
            title=title,
            assignee=application.owner,
            due_on=due_on,
            created_on=today,
            source_event_id=source_event_id,
        )
        self.tasks[task.task_id] = task
        if kind is TaskKind.REJECTION:
            application.has_rejection = True
        self.log(today, by, f"分派任务·{kind.value}", task.task_id, f"{title}（责任人 {task.assignee}，期限 {due_on}）")
        return task

    def request_supplement(
        self, application_id: str, title: str, due_on: date, today: date, by: str
    ) -> Task:
        return self._add_task(
            self.applications[application_id], TaskKind.SUPPLEMENT, title, due_on, today, by
        )

    def record_rejection(
        self, application_id: str, title: str, due_on: date, today: date, by: str
    ) -> Task:
        return self._add_task(
            self.applications[application_id], TaskKind.REJECTION, title, due_on, today, by
        )

    def complete_task(self, task_id: str, today: date, by: str) -> None:
        task = self.tasks[task_id]
        task.status = TaskStatus.DONE
        application = self.applications[task.application_id]
        if task.kind is TaskKind.REJECTION and not any(
            t.status is TaskStatus.OPEN
            and t.kind is TaskKind.REJECTION
            and t.application_id == application.application_id
            for t in self.tasks.values()
        ):
            application.has_rejection = False
        self.log(today, by, "任务完成", task_id, task.title)

    def record_decision(
        self,
        application_id: str,
        outcome: str,
        by: str,
        today: date,
        evidence_refs: tuple[tuple[str, str], ...] | None = None,
    ) -> AccessDecision:
        """登记准入判断；默认定格正式申报包内的证据版本。"""

        application = self.applications[application_id]
        if evidence_refs is None:
            evidence_refs = tuple(
                (self.get_version(vid).item_id, vid) for vid in application.filed_package
            )
        stale: list[str] = []
        for item_id, version_id in evidence_refs:
            current = self.current_version(item_id, today)
            if current is None or current.version_id != version_id:
                version = self.get_version(version_id)
                stale.append(f"{self.items[item_id].title} v{version.version_no}")
        if stale:
            raise FilingError([f"准入判断引用了非现行版本：{', '.join(stale)}"])
        decision = AccessDecision(
            decision_id=self._id("DEC"),
            application_id=application_id,
            outcome=outcome,
            decided_by=by,
            decided_on=today,
            evidence_refs=evidence_refs,
        )
        self.decisions.append(decision)
        self.log(today, by, "准入判断", decision.decision_id, f"{outcome}；证据 {', '.join(v for _, v in evidence_refs)}")
        return decision

    def approve(self, application_id: str, by: str, today: date) -> None:
        application = self.applications[application_id]
        if application.stage is Stage.INITIAL_CONTACT:
            raise FilingError(["尚未正式申报，不能获批"])
        if application.has_rejection:
            raise FilingError(["存在未整改完成的驳回项，不能获批"])
        application.stage = Stage.APPROVED
        self.log(today, by, "阶段推进", application_id, "获批上市")

    def start_use(self, application_id: str, by: str, today: date) -> None:
        application = self.applications[application_id]
        if application.stage is not Stage.APPROVED:
            raise FilingError(["仅获批上市的申请可转入实际使用"])
        application.stage = Stage.IN_USE
        self.log(today, by, "阶段推进", application_id, "实际使用")

    def open_tasks(self, application_id: str) -> list[Task]:
        return [
            t
            for t in self.tasks.values()
            if t.application_id == application_id and t.status is TaskStatus.OPEN
        ]

    def overdue_tasks(self, today: date) -> list[Task]:
        return [t for t in self.tasks.values() if t.is_overdue(today)]

    # ---------------------------------------------------------- 下一步行动

    def next_actions(self, application: Application, today: date) -> list[str]:
        path = self.path_of(application)
        open_tasks = self.open_tasks(application.application_id)
        actions: list[str] = []

        for task in open_tasks:
            flag = "（已逾期）" if task.is_overdue(today) else f"（期限 {task.due_on}）"
            actions.append(
                f"{task.kind.value}：{task.title} → 责任人 {task.assignee}{flag}"
            )

        if application.stage is Stage.INITIAL_CONTACT:
            if not open_tasks:
                covered_kinds = {
                    item.kind
                    for item in self.items.values()
                    if item.enterprise_id == application.enterprise_id
                    and item.covers(path)
                    and self.current_version(item.item_id, today) is not None
                }
                for kind in path.required_evidence:
                    if kind not in covered_kinds:
                        actions.append(f"补充{path.country}路径所需{kind.value}")
                if path.requires_local_agent and not path.agent_id:
                    actions.append(f"指定{path.country}本地代理并备案授权书")
                if not actions:
                    actions.append("资料齐备，可按现行版本正式提交申报")
        elif application.stage is Stage.FORMAL_SUBMISSION:
            if not open_tasks:
                actions.append("等待监管审评，按受理号跟进进度")
        elif application.stage is Stage.APPROVED:
            expiring = self._expiring_filed_certificates(application, today)
            for item, version in expiring:
                actions.append(f"《{item.title}》将于 {version.valid_until} 到期，提前办理续期")
            channel = path.procurement_channel
            if channel:
                actions.append(f"对接{path.country}{channel}，推动入院与挂网采购")
        else:
            expiring = self._expiring_filed_certificates(application, today)
            for item, version in expiring:
                actions.append(f"《{item.title}》将于 {version.valid_until} 到期，提前办理续期")
            actions.append("收集临床使用与不良事件数据，维持上市后合规")
        return actions

    def _expiring_filed_certificates(
        self, application: Application, today: date
    ) -> list[tuple[EvidenceItem, EvidenceVersion]]:
        horizon = today + timedelta(days=RENEWAL_NOTICE_DAYS)
        rows = []
        for item, version, _ in self.filed_evidence(application, today):
            if (
                item.kind is EvidenceKind.CERTIFICATE
                and version.valid_until is not None
                and today <= version.valid_until <= horizon
            ):
                rows.append((item, version))
        return rows

    # ---------------------------------------------------------- 变更影响

    def apply_change(self, event: ChangeEvent, by: str = "系统监测") -> ImpactReport:
        if not event.event_id:
            event.event_id = self._id("EVT")
        self.events.append(event)
        impacted: list[Impact] = []

        if event.kind is ChangeKind.CERTIFICATE_EXPIRED:
            impacted = self._impact_certificate(event, by)
        elif event.kind is ChangeKind.INDICATION_ADJUSTED:
            impacted = self._impact_product_change(event, by, indication=True)
        elif event.kind is ChangeKind.SITE_CHANGED:
            impacted = self._impact_product_change(event, by, indication=False)
        elif event.kind is ChangeKind.AGENT_TERMINATED:
            impacted = self._impact_agent(event, by)

        report = ImpactReport(event=event, impacts=impacted)
        self.impacts.append(report)
        self.log(
            event.occurred_on,
            by,
            f"变更影响分析·{event.kind.value}",
            event.event_id,
            f"{event.note}；受影响申请 {len(impacted)} 件",
        )
        return report

    def _impact_certificate(self, event: ChangeEvent, by: str) -> list[Impact]:
        item = self.items[event.item_id]
        for version in self.versions.get(item.item_id, []):
            if (
                version.status is VersionStatus.CURRENT
                and version.valid_until is not None
                and version.valid_until <= event.occurred_on
            ):
                version.status = VersionStatus.EXPIRED
        impacts: list[Impact] = []
        for application in self._applications_for_product(item.product_id):
            path = self.path_of(application)
            if not item.covers(path):
                continue
            if application.stage is Stage.INITIAL_CONTACT:
                continue  # 尚未递交，直接改用新版即可，不构成受影响申请
            task = self._add_task(
                application,
                TaskKind.RENEWAL,
                f"《{item.title}》已到期，提交新版证书完成续期",
                event.occurred_on + timedelta(days=DEFAULT_RENEWAL_DAYS),
                event.occurred_on,
                by,
                event.event_id,
            )
            impacts.append(
                Impact(application.application_id, f"申报依据的《{item.title}》已到期", task.task_id)
            )
        return impacts

    def _impact_product_change(
        self, event: ChangeEvent, by: str, *, indication: bool
    ) -> list[Impact]:
        product = self.products[event.product_id]
        if indication:
            product.indication = event.note
        else:
            product.production_site = event.note
        label = "适应症" if indication else "生产场地"
        impacts: list[Impact] = []
        for application in self._applications_for_product(product.product_id):
            if application.stage is Stage.INITIAL_CONTACT:
                continue  # 尚未递交，按新内容准备即可
            task = self._add_task(
                application,
                TaskKind.VARIATION,
                f"产品{label}变化，向监管机构办理变更申报并更新技术资料",
                event.occurred_on + timedelta(days=DEFAULT_VARIATION_DAYS),
                event.occurred_on,
                by,
                event.event_id,
            )
            impacts.append(
                Impact(application.application_id, f"产品{label}已变化：{event.note}", task.task_id)
            )
        return impacts

    def _impact_agent(self, event: ChangeEvent, by: str) -> list[Impact]:
        impacted_paths = [
            path
            for path in self.paths.values()
            if path.agent_id == event.agent_id
        ]
        impacts: list[Impact] = []
        for path in impacted_paths:
            path.agent_id = None
            for application in self._applications_for_path(path.path_id):
                task = self._add_task(
                    application,
                    TaskKind.VARIATION,
                    f"本地代理（{event.note}）已终止，重新指定代理并向监管机构报备",
                    event.occurred_on + timedelta(days=DEFAULT_VARIATION_DAYS),
                    event.occurred_on,
                    by,
                    event.event_id,
                )
                impacts.append(
                    Impact(
                        application.application_id,
                        f"{path.country}本地代理已终止，注册授权链中断",
                        task.task_id,
                    )
                )
        return impacts

    def _applications_for_product(self, product_id: str) -> list[Application]:
        return [
            a
            for a in self.applications.values()
            if self.path_of(a).product_id == product_id
        ]

    def _applications_for_path(self, path_id: str) -> list[Application]:
        return [a for a in self.applications.values() if a.path_id == path_id]

    # ---------------------------------------------------------- 阶段视图

    def applications_by_stage(
        self, actor: Actor | None = None
    ) -> dict[Stage, list[Application]]:
        apps = self.visible_applications(actor) if actor else list(self.applications.values())
        grouped: dict[Stage, list[Application]] = {stage: [] for stage in STAGE_ORDER}
        for application in apps:
            grouped[application.stage].append(application)
        return grouped
