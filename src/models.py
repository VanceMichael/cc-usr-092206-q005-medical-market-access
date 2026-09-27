"""创新药械东盟准入工作台的核心模型。

同一产品在每个目标国家有独立的注册路径；证书、试验数据、翻译件等
资料按适用范围关联到路径，并以版本管理，防止旧版资料被拿去申报。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum


class Role(Enum):
    SERVICE_ORG = "区域服务机构"
    ENTERPRISE = "企业"
    PARTNER = "合作方"


@dataclass(frozen=True)
class Actor:
    """工作台使用者；企业与合作方只能看到被授权的资料。"""

    actor_id: str
    name: str
    role: Role
    enterprise_id: str | None = None


class Stage(Enum):
    INITIAL_CONTACT = "初步接洽"
    FORMAL_SUBMISSION = "正式申报"
    APPROVED = "获批上市"
    IN_USE = "实际使用"


STAGE_ORDER = (
    Stage.INITIAL_CONTACT,
    Stage.FORMAL_SUBMISSION,
    Stage.APPROVED,
    Stage.IN_USE,
)


class EvidenceKind(Enum):
    CERTIFICATE = "证书"
    TRIAL_DATA = "试验数据"
    TRANSLATION = "翻译件"
    HOSPITAL_PARTNERSHIP = "合作医院"
    DISTRIBUTION_LICENSE = "经销资质"
    PROCUREMENT_OPPORTUNITY = "集采机会"


class VersionStatus(Enum):
    CURRENT = "现行有效"
    SUPERSEDED = "已被替代"
    EXPIRED = "已到期"
    REVOKED = "已作废"


class TaskKind(Enum):
    SUPPLEMENT = "补件"
    REJECTION = "驳回整改"
    RENEWAL = "证书续期"
    VARIATION = "变更应对"


class TaskStatus(Enum):
    OPEN = "待处理"
    DONE = "已完成"


class ChangeKind(Enum):
    CERTIFICATE_EXPIRED = "证书到期"
    INDICATION_ADJUSTED = "适应症调整"
    SITE_CHANGED = "生产场地变化"
    AGENT_TERMINATED = "代理终止"


@dataclass
class Product:
    product_id: str
    enterprise_id: str
    name: str
    indication: str
    production_site: str


@dataclass
class RegistrationPath:
    """同一产品在不同目标国家各自独立的注册路径与法规来源。"""

    path_id: str
    product_id: str
    country: str
    product_class: str
    label_language: str
    regulatory_source: str
    requires_local_agent: bool
    agent_id: str | None = None
    procurement_channel: str | None = None
    required_evidence: tuple[EvidenceKind, ...] = ()


@dataclass
class EvidenceItem:
    """按适用范围关联的准入资料；countries 为空表示适用全部目标国。"""

    item_id: str
    enterprise_id: str
    product_id: str
    kind: EvidenceKind
    title: str
    countries: frozenset[str] = frozenset()
    shared_with: frozenset[str] = frozenset()

    def covers(self, path: RegistrationPath) -> bool:
        return self.product_id == path.product_id and (
            not self.countries or path.country in self.countries
        )


@dataclass
class EvidenceVersion:
    version_id: str
    item_id: str
    version_no: int
    issued_on: date
    summary: str
    valid_until: date | None = None
    status: VersionStatus = VersionStatus.CURRENT


@dataclass
class Application:
    """一个产品在某一目标国家的准入申请，逐级推进四个阶段。"""

    application_id: str
    enterprise_id: str
    path_id: str
    owner: str
    created_on: date
    stage: Stage = Stage.INITIAL_CONTACT
    filed_package: tuple[str, ...] = ()
    filed_on: date | None = None
    has_rejection: bool = False


@dataclass
class AccessDecision:
    """准入判断；evidence_refs 定格判断所采用的每一份证据版本。"""

    decision_id: str
    application_id: str
    outcome: str
    decided_by: str
    decided_on: date
    evidence_refs: tuple[tuple[str, str], ...]


@dataclass
class Task:
    """补件、驳回整改等必须落到责任人和期限的工作项。"""

    task_id: str
    application_id: str
    kind: TaskKind
    title: str
    assignee: str
    due_on: date
    created_on: date
    status: TaskStatus = TaskStatus.OPEN
    source_event_id: str | None = None

    def is_overdue(self, today: date) -> bool:
        return self.status is TaskStatus.OPEN and self.due_on < today


@dataclass
class ChangeEvent:
    kind: ChangeKind
    occurred_on: date
    note: str
    event_id: str = ""
    product_id: str | None = None
    item_id: str | None = None
    agent_id: str | None = None


@dataclass
class Impact:
    application_id: str
    reason: str
    task_id: str


@dataclass
class ImpactReport:
    event: ChangeEvent
    impacts: list[Impact]
