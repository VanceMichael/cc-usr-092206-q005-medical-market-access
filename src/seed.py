"""演示场景：一家广西创新医疗器械企业同时进入三个东盟国家。

三个目标国在产品分类、临床证据、标签语言、医保采购和本地代理要求上各不相同；
另有一家企业和一个旧合作方，用于验证资料隔离与旧版申报拦截。
"""

from __future__ import annotations

from datetime import date

from .models import (
    Actor,
    Application,
    ChangeEvent,
    ChangeKind,
    EvidenceItem,
    EvidenceKind,
    EvidenceVersion,
    Product,
    RegistrationPath,
    Role,
    Stage,
    VersionStatus,
)
from .services import Workbench

TODAY = date(2026, 9, 27)


def build() -> Workbench:
    wb = Workbench()

    # -------------------------------------------------------------- 使用者

    service = Actor("ORG-1", "广西东盟药械准入服务中心", Role.SERVICE_ORG)
    company = Actor(
        "ENT-1", "桂创医疗器械有限公司", Role.ENTERPRISE, enterprise_id="E1"
    )
    other = Actor(
        "ENT-2", "邻省医械科技有限公司", Role.ENTERPRISE, enterprise_id="E2"
    )
    old_partner = Actor("P-OLD", "旧版资料合作方", Role.PARTNER)
    th_agent = Actor("P-TH", "曼谷本地注册代理", Role.PARTNER)
    vn_agent = Actor("P-VN", "河内本地注册代理", Role.PARTNER)
    id_agent = Actor("P-ID", "雅加达本地注册代理", Role.PARTNER)
    my_agent = Actor("P-MY", "吉隆坡本地注册代理", Role.PARTNER)
    for actor in (service, company, other, old_partner, th_agent, vn_agent, id_agent, my_agent):
        wb.actors[actor.actor_id] = actor

    # -------------------------------------------------------------- 产品

    product = Product(
        "P1",
        "E1",
        "智能血管介入导航系统 VasoNav",
        "外周血管介入术中导航",
        "广西南宁一号生产场地",
    )
    other_product = Product("P2", "E2", "某企业自持产品", "示例适应症", "外省场地")
    wb.products[product.product_id] = product
    wb.products[other_product.product_id] = other_product

    # ---------------------------------------- 三个国家各自独立的注册路径

    paths = [
        RegistrationPath(
            path_id="PATH-TH",
            product_id="P1",
            country="泰国",
            product_class="按泰国 FDA 风险分类为第 4 类（高风险）",
            label_language="泰文标签并随附英文说明书",
            regulatory_source="泰国 FDA Medical Device Act B.E. 2551 及 ASEAN AMDR 分类指引",
            requires_local_agent=True,
            agent_id="P-TH",
            procurement_channel="UCEP 医保支付通道与公立医院招标",
            required_evidence=(
                EvidenceKind.CERTIFICATE,
                EvidenceKind.TRIAL_DATA,
                EvidenceKind.TRANSLATION,
                EvidenceKind.HOSPITAL_PARTNERSHIP,
                EvidenceKind.DISTRIBUTION_LICENSE,
            ),
        ),
        RegistrationPath(
            path_id="PATH-VN",
            product_id="P1",
            country="越南",
            product_class="按 36/2016/ND-CP 归为 C/D 类高风险器械",
            label_language="越南文标签",
            regulatory_source="越南卫生部 98/2021/ND-CP 法令及 19/2021/TT-BYT 通告",
            requires_local_agent=True,
            agent_id="P-VN",
            procurement_channel="医保目录与省级集中采购",
            required_evidence=(
                EvidenceKind.CERTIFICATE,
                EvidenceKind.TRIAL_DATA,
                EvidenceKind.TRANSLATION,
                EvidenceKind.DISTRIBUTION_LICENSE,
            ),
        ),
        RegistrationPath(
            path_id="PATH-ID",
            product_id="P1",
            country="印度尼西亚",
            product_class="按 Kemenkes 62/2017 归为 C 类",
            label_language="印尼文标签",
            regulatory_source="印尼 Permenkes 62/2017 及在线注册系统 Regalkes",
            requires_local_agent=True,
            agent_id="P-ID",
            procurement_channel="e-Catalog 政府集采与公立医院准入",
            required_evidence=(
                EvidenceKind.CERTIFICATE,
                EvidenceKind.TRIAL_DATA,
                EvidenceKind.TRANSLATION,
                EvidenceKind.HOSPITAL_PARTNERSHIP,
                EvidenceKind.DISTRIBUTION_LICENSE,
                EvidenceKind.PROCUREMENT_OPPORTUNITY,
            ),
        ),
        RegistrationPath(
            path_id="PATH-MY",
            product_id="P1",
            country="马来西亚",
            product_class="按 MDA Act 737 归为 Class C（中高风险）",
            label_language="马来文与英文双语标签",
            regulatory_source="马来西亚 Medical Device Act 737 及 MDA 注册指南（MeDC@St）",
            requires_local_agent=True,
            agent_id="P-MY",
            procurement_channel="PhEDA 私人医院联采与公立医院招标",
            required_evidence=(
                EvidenceKind.CERTIFICATE,
                EvidenceKind.TRIAL_DATA,
                EvidenceKind.TRANSLATION,
                EvidenceKind.DISTRIBUTION_LICENSE,
            ),
        ),
    ]
    for path in paths:
        wb.paths[path.path_id] = path

    # -------------------------------------------------------------- 资料

    def add_item(
        item_id: str,
        kind: EvidenceKind,
        title: str,
        countries: set[str] | None,
        versions: list[EvidenceVersion],
        *,
        shared_with: frozenset[str] = frozenset(),
        enterprise_id: str = "E1",
        product_id: str = "P1",
    ) -> None:
        item = EvidenceItem(
            item_id=item_id,
            enterprise_id=enterprise_id,
            product_id=product_id,
            kind=kind,
            title=title,
            countries=frozenset(countries) if countries is not None else frozenset(),
            shared_with=shared_with,
        )
        wb.items[item_id] = item
        wb.versions[item_id] = versions

    # 证书：泰越共用一版（适用范围不含印尼），印尼单独办证
    add_item(
        "EV-CERT-SEA",
        EvidenceKind.CERTIFICATE,
        "自由销售证书 CFS（泰越互认版）",
        {"泰国", "越南"},
        [
            EvidenceVersion(
                "VER-101", "EV-CERT-SEA", 1, date(2023, 6, 1),
                "2023 版证书", date(2026, 9, 30), VersionStatus.SUPERSEDED,
            ),
            EvidenceVersion(
                "VER-102", "EV-CERT-SEA", 2, date(2026, 6, 15),
                "2026 换发证书，有效期至 2029-06-14", date(2029, 6, 14),
            ),
        ],
        # 旧合作方仅在历史合作中拿到过第 1 版对应资料的授权
        shared_with=frozenset({"P-OLD"}),
    )
    add_item(
        "EV-CERT-ID",
        EvidenceKind.CERTIFICATE,
        "印尼注册证书（即将到期，演示到期联动）",
        {"印度尼西亚"},
        [
            EvidenceVersion(
                "VER-111", "EV-CERT-ID", 1, date(2021, 10, 20),
                "印尼首版注册证", date(2026, 10, 20),
            )
        ],
    )
    add_item(
        "EV-TRIAL",
        EvidenceKind.TRIAL_DATA,
        "多中心临床试验报告",
        None,  # 三国通用
        [
            EvidenceVersion(
                "VER-201", "EV-TRIAL", 1, date(2024, 3, 1),
                "初版试验报告（样本量 120）", status=VersionStatus.SUPERSEDED
            ),
            EvidenceVersion(
                "VER-202", "EV-TRIAL", 2, date(2026, 4, 10),
                "补充随访至 24 个月的现行试验报告"
            ),
        ],
    )
    add_item(
        "EV-TRANS-TH",
        EvidenceKind.TRANSLATION,
        "泰文标签与说明书翻译件",
        {"泰国"},
        [EvidenceVersion("VER-301", "EV-TRANS-TH", 1, date(2026, 5, 1), "泰文译件（母语译员签章）")],
    )
    add_item(
        "EV-TRANS-VN",
        EvidenceKind.TRANSLATION,
        "越南文标签翻译件",
        {"越南"},
        [EvidenceVersion("VER-302", "EV-TRANS-VN", 1, date(2026, 5, 20), "越南文译件")],
    )
    add_item(
        "EV-TRANS-ID",
        EvidenceKind.TRANSLATION,
        "印尼文标签翻译件",
        {"印度尼西亚"},
        [EvidenceVersion("VER-303", "EV-TRANS-ID", 1, date(2026, 7, 5), "印尼文译件")],
    )
    add_item(
        "EV-HOSP-TH",
        EvidenceKind.HOSPITAL_PARTNERSHIP,
        "曼谷 Siriraj 医院临床合作协议",
        {"泰国"},
        [EvidenceVersion("VER-401", "EV-HOSP-TH", 1, date(2026, 6, 1), "泰国路径合作医院")],
    )
    add_item(
        "EV-HOSP-ID",
        EvidenceKind.HOSPITAL_PARTNERSHIP,
        "雅加达 Cipto 医院试用合作意向",
        {"印度尼西亚"},
        [EvidenceVersion("VER-402", "EV-HOSP-ID", 1, date(2026, 8, 12), "印尼路径合作医院")],
    )
    add_item(
        "EV-DIST",
        EvidenceKind.DISTRIBUTION_LICENSE,
        "东盟区域经销资质与进口商许可",
        None,
        [EvidenceVersion("VER-501", "EV-DIST", 1, date(2026, 2, 1), "经三国使馆认证的经销资质")],
    )
    add_item(
        "EV-PROC-ID",
        EvidenceKind.PROCUREMENT_OPPORTUNITY,
        "印尼 e-Catalog 集采挂网机会",
        {"印度尼西亚"},
        [EvidenceVersion("VER-601", "EV-PROC-ID", 1, date(2026, 9, 1), "2026 Q4 集采窗口资料")],
    )
    add_item(
        "EV-CERT-MY",
        EvidenceKind.CERTIFICATE,
        "马来西亚 MDA 注册证书",
        {"马来西亚"},
        [EvidenceVersion("VER-121", "EV-CERT-MY", 1, date(2025, 3, 10), "MDA 注册证（2025 获批）")],
    )
    add_item(
        "EV-TRANS-MY",
        EvidenceKind.TRANSLATION,
        "马来文与英文双语标签翻译件",
        {"马来西亚"},
        [EvidenceVersion("VER-304", "EV-TRANS-MY", 1, date(2025, 4, 2), "双语标签译件")],
    )
    add_item(
        "EV-OTHER",
        EvidenceKind.CERTIFICATE,
        "邻省企业自有证书（隔离验证用）",
        None,
        [EvidenceVersion("VER-901", "EV-OTHER", 1, date(2026, 1, 1), "其他企业资料")],
        enterprise_id="E2",
        product_id="P2",
    )

    # -------------------------------------------------------------- 申请

    th_app = Application(
        "APP-TH", "E1", "PATH-TH", "李注册（企业RA）", date(2026, 7, 10),
        stage=Stage.FORMAL_SUBMISSION,
        filed_package=("VER-102", "VER-202", "VER-301", "VER-401", "VER-501"),
        filed_on=date(2026, 8, 18),
    )
    vn_app = Application(
        "APP-VN", "E1", "PATH-VN", "王准入（企业RA）", date(2026, 5, 6),
        stage=Stage.APPROVED,
        filed_package=("VER-102", "VER-202", "VER-302", "VER-501"),
        filed_on=date(2026, 6, 2),
    )
    id_app = Application(
        "APP-ID", "E1", "PATH-ID", "陈项目经理（服务机构）", date(2026, 9, 20),
        stage=Stage.INITIAL_CONTACT,
    )
    my_app = Application(
        "APP-MY", "E1", "PATH-MY", "王准入（企业RA）", date(2025, 11, 3),
        stage=Stage.APPROVED,
        filed_package=("VER-121", "VER-202", "VER-304", "VER-501"),
        filed_on=date(2026, 5, 20),
    )
    for app in (th_app, vn_app, id_app, my_app):
        wb.applications[app.application_id] = app

    # 越南准入判断：定格当时采用的证据版本，供管理者事后核对
    wb.record_decision(
        "APP-VN",
        "符合越南 C 类器械准入条件，批准注册",
        "服务机构评审组",
        date(2026, 8, 28),
        evidence_refs=(
            ("EV-CERT-SEA", "VER-102"),
            ("EV-TRIAL", "VER-202"),
            ("EV-TRANS-VN", "VER-302"),
            ("EV-DIST", "VER-501"),
        ),
    )
    wb.record_decision(
        "APP-MY",
        "符合马来西亚 Class C 器械注册条件，批准上市",
        "服务机构评审组",
        date(2026, 7, 30),
        evidence_refs=(
            ("EV-CERT-MY", "VER-121"),
            ("EV-TRIAL", "VER-202"),
            ("EV-TRANS-MY", "VER-304"),
            ("EV-DIST", "VER-501"),
        ),
    )

    # 泰国审评中：一次补件、一次驳回，均落到责任人与期限
    wb.request_supplement(
        "APP-TH", "补充泰文标签灭菌方式说明", date(2026, 10, 12),
        date(2026, 9, 25), "泰国 FDA 受理处",
    )
    wb.record_rejection(
        "APP-TH", "临床报告亚组数据需按泰方格式重整", date(2026, 10, 18),
        date(2026, 9, 26), "泰国 FDA 审评员",
    )

    return wb


if __name__ == "__main__":  # pragma: no cover
    build()
