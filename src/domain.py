"""读取并检查共享的领域资料。

load_domain 保留原有基础校验；load_workbench 在其之上补充
统一准入工作台所需的引用完整性与版本钉版校验。
"""

import json
from pathlib import Path

STAGES = ("lead", "filing", "approved", "in_use")
ARTIFACT_TYPES = ("certificate", "clinical", "label", "hospital", "distribution", "procurement")
EVENT_TYPES = ("certificate_expiry", "indication_change", "site_change", "agent_termination")


def load_domain(path: Path) -> dict:
    """返回字段完整且带版本的业务资料。"""
    value = json.loads(path.read_text(encoding="utf-8"))
    required = {"domain", "version", "sample_id", "actors", "facts", "constraints"}
    if not required.issubset(value):
        raise ValueError("共享资料缺少必要字段")
    if value["version"] < 1 or len(value["actors"]) < 2 or len(value["facts"]) < 2 or len(value["constraints"]) < 2:
        raise ValueError("共享资料内容不完整")
    return value


def _fail(message: str) -> None:
    raise ValueError(f"工作台资料不完整：{message}")


def _index(rows: list, key: str, label: str) -> dict:
    table = {}
    for row in rows:
        ident = row.get(key)
        if not ident:
            _fail(f"{label}缺少标识")
        if ident in table:
            _fail(f"{label}标识重复：{ident}")
        table[ident] = row
    return table


def _require(condition: bool, message: str) -> None:
    if not condition:
        _fail(message)


def load_workbench(path: Path) -> dict:
    """返回通过引用完整性校验的工作台资料。"""
    data = load_domain(path)
    for section in ("pipeline_stages", "countries", "regulations", "organizations", "products",
                    "paths", "artifacts", "applications", "authorizations", "actions",
                    "decisions", "events"):
        _require(isinstance(data.get(section), list), f"缺少 {section} 列表")

    stages = _index(data["pipeline_stages"], "id", "阶段")
    _require(set(stages) == set(STAGES), "阶段必须覆盖初步接洽、正式申报、获批上市、实际使用")

    countries = _index(data["countries"], "id", "国家")
    regulations = _index(data["regulations"], "id", "法规")
    orgs = _index(data["organizations"], "id", "机构")
    products = _index(data["products"], "id", "产品")
    paths = _index(data["paths"], "id", "注册路径")
    artifacts = _index(data["artifacts"], "id", "资料")
    applications = _index(data["applications"], "id", "申请")

    enterprises = [o for o in orgs.values() if o["type"] == "enterprise"]
    _require(any(o["type"] == "service_org" for o in orgs.values()), "缺少区域服务机构")
    _require(len(enterprises) >= 2, "至少需要两家企业以验证资料隔离")

    for reg in regulations.values():
        _require(reg["country"] in countries, f"法规 {reg['id']} 的国家不存在")

    for product in products.values():
        _require(product["owner_org"] in orgs, f"产品 {product['id']} 的持有机构不存在")
        _require(orgs[product["owner_org"]]["type"] == "enterprise",
                 f"产品 {product['id']} 的持有机构必须是企业")

    for path_row in paths.values():
        _require(path_row["product"] in products, f"路径 {path_row['id']} 的产品不存在")
        _require(path_row["country"] in countries, f"路径 {path_row['id']} 的国家不存在")
        for ref in path_row["regulation_refs"]:
            _require(ref in regulations, f"路径 {path_row['id']} 引用的法规 {ref} 不存在")
            _require(regulations[ref]["country"] == path_row["country"],
                     f"路径 {path_row['id']} 引用了他国法规 {ref}")

    for artifact in artifacts.values():
        _require(artifact["type"] in ARTIFACT_TYPES, f"资料 {artifact['id']} 类型非法")
        _require(artifact["owner_org"] in orgs, f"资料 {artifact['id']} 的持有机构不存在")
        for product_id in artifact["applies_to"]["products"]:
            _require(product_id in products, f"资料 {artifact['id']} 关联的产品 {product_id} 不存在")
        for country_id in artifact["applies_to"]["countries"]:
            _require(country_id in countries, f"资料 {artifact['id']} 关联的国家 {country_id} 不存在")
        versions = [v["version"] for v in artifact["versions"]]
        _require(len(versions) == len(set(versions)), f"资料 {artifact['id']} 的版本号重复")

    def check_pinned(entry: dict, where: str) -> None:
        artifact = artifacts.get(entry["artifact"])
        _require(artifact is not None, f"{where} 引用的资料 {entry['artifact']} 不存在")
        pinned = {v["version"] for v in artifact["versions"]}
        _require(entry["version"] in pinned,
                 f"{where} 钉住的 {entry['artifact']} {entry['version']} 不存在")

    for app in applications.values():
        _require(app["product"] in products, f"申请 {app['id']} 的产品不存在")
        _require(app["country"] in countries, f"申请 {app['id']} 的国家不存在")
        path_row = paths.get(app["path"])
        _require(path_row is not None, f"申请 {app['id']} 的注册路径不存在")
        _require(path_row["product"] == app["product"] and path_row["country"] == app["country"],
                 f"申请 {app['id']} 与路径 {app['path']} 的产品或国家不一致")
        _require(app["stage"] in STAGES, f"申请 {app['id']} 的阶段非法")
        _require(app["stage_history"][-1]["stage"] == app["stage"],
                 f"申请 {app['id']} 的当前阶段与阶段履历不一致")
        if "agent_org" in app:
            _require(app["agent_org"] in orgs, f"申请 {app['id']} 的代理机构不存在")
        for entry in app["dossier"]:
            check_pinned(entry, f"申请 {app['id']} 的卷宗")

    for grant in data["authorizations"]:
        _require(grant["org"] in orgs, f"授权的机构 {grant['org']} 不存在")
        _require(grant["artifact"] in artifacts, f"授权的资料 {grant['artifact']} 不存在")

    for action in data["actions"]:
        _require(action["application"] in applications, f"待办 {action['id']} 的申请不存在")
        _require(action["owner"]["org"] in orgs, f"待办 {action['id']} 的责任机构不存在")
        if action["status"] == "resolved":
            _require(bool(action.get("resolved_on")), f"待办 {action['id']} 已办结但缺少办结日期")

    for decision in data["decisions"]:
        _require(decision["application"] in applications, f"判断 {decision['id']} 的申请不存在")
        _require(decision["decided_by"] in orgs, f"判断 {decision['id']} 的作出机构不存在")
        for entry in decision["evidence"]:
            check_pinned(entry, f"判断 {decision['id']} 的证据")

    for event in data["events"]:
        _require(event["type"] in EVENT_TYPES, f"事件 {event['id']} 类型非法")
        if event["type"] == "certificate_expiry":
            _require(event.get("artifact") in artifacts, f"事件 {event['id']} 的证书不存在")
        elif event["type"] in ("indication_change", "site_change"):
            _require(event.get("product") in products, f"事件 {event['id']} 的产品不存在")
        elif event["type"] == "agent_termination":
            _require(event.get("org") in orgs, f"事件 {event['id']} 的机构不存在")

    return data
