"""统一准入工作台的核心服务。

面向广西区域服务机构：按查看者过滤可见范围，输出四阶段工作台视图、
补件/驳回待办、变更影响分析、旧版申报识别与准入判断证据稽核。
所有函数只读取 load_workbench 校验过的资料，不做写操作。
"""

from __future__ import annotations

from datetime import date

STAGE_ORDER = ("lead", "filing", "approved", "in_use")
STAGE_NAMES = {
    "lead": "初步接洽",
    "filing": "正式申报",
    "approved": "获批上市",
    "in_use": "实际使用",
}
EVENT_TYPE_NAMES = {
    "certificate_expiry": "证书到期",
    "indication_change": "适应症调整",
    "site_change": "生产场地变化",
    "agent_termination": "代理终止",
}
ACTION_KIND_NAMES = {"supplement": "补件", "rejection": "驳回", "todo": "待办"}
EXPIRY_WARNING_DAYS = 90
NEW_AGENT_GRACE_DAYS = 30


def parse_day(value) -> date:
    """把 ISO 日期字符串或 date 统一成 date。"""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def build_index(data: dict) -> dict:
    """把各列表转成 id 索引，便于服务函数查询。"""
    return {
        "stages": {s["id"]: s for s in data["pipeline_stages"]},
        "countries": {c["id"]: c for c in data["countries"]},
        "regulations": {r["id"]: r for r in data["regulations"]},
        "orgs": {o["id"]: o for o in data["organizations"]},
        "products": {p["id"]: p for p in data["products"]},
        "paths": {p["id"]: p for p in data["paths"]},
        "artifacts": {a["id"]: a for a in data["artifacts"]},
        "applications": {a["id"]: a for a in data["applications"]},
    }


def current_version(artifact: dict) -> dict:
    """资料当前有效版本：按签发日期取最新。"""
    return max(artifact["versions"], key=lambda v: v["issued_on"])


def version_of(artifact: dict, version_id: str) -> dict | None:
    for version in artifact["versions"]:
        if version["version"] == version_id:
            return version
    return None


def org_name(idx: dict, org_id: str) -> str:
    org = idx["orgs"].get(org_id)
    return org["name"] if org else org_id


def _require_viewer(idx: dict, viewer: str) -> dict:
    org = idx["orgs"].get(viewer)
    if org is None:
        raise ValueError(f"查看者不存在：{viewer}")
    return org


def _product_owner(idx: dict, product_id: str) -> str:
    return idx["products"][product_id]["owner_org"]


def visible_applications(data: dict, viewer: str) -> list[dict]:
    """查看者可见的申请：服务机构全部可见；企业看自有产品；代理看所代理的申请。"""
    idx = build_index(data)
    org = _require_viewer(idx, viewer)
    if org["type"] == "service_org":
        return list(idx["applications"].values())
    result = []
    for app in idx["applications"].values():
        if _product_owner(idx, app["product"]) == viewer or app.get("agent_org") == viewer:
            result.append(app)
    return result


def visible_artifacts(data: dict, viewer: str) -> list[dict]:
    """查看者可见的资料。

    规则：持有机构、被有效授权的机构、服务机构可见；集采机会对适用产品的
    持有企业公开；可见申请卷宗中钉住的资料随申请一并可见。未经授权的企业
    资料互相不可见。
    """
    idx = build_index(data)
    org = _require_viewer(idx, viewer)
    if org["type"] == "service_org":
        return list(idx["artifacts"].values())
    granted = {
        g["artifact"]
        for g in data["authorizations"]
        if g["org"] == viewer and g["status"] == "active"
    }
    dossier_refs = {
        entry["artifact"]
        for app in visible_applications(data, viewer)
        for entry in app["dossier"]
    }
    result = []
    for artifact in idx["artifacts"].values():
        if artifact["owner_org"] == viewer or artifact["id"] in granted or artifact["id"] in dossier_refs:
            result.append(artifact)
            continue
        if artifact["type"] == "procurement" and any(
            _product_owner(idx, p) == viewer for p in artifact["applies_to"]["products"]
        ):
            result.append(artifact)
    return result


def _visible_decisions(data: dict, viewer: str) -> list[dict]:
    visible_ids = {app["id"] for app in visible_applications(data, viewer)}
    return [d for d in data["decisions"] if d["application"] in visible_ids]


def _visible_events(data: dict, viewer: str) -> list[dict]:
    idx = build_index(data)
    org = _require_viewer(idx, viewer)
    if org["type"] == "service_org":
        return list(data["events"])
    visible_apps = visible_applications(data, viewer)
    visible_products = {app["product"] for app in visible_apps}
    result = []
    for event in data["events"]:
        if event["type"] == "agent_termination":
            if any(app.get("agent_org") == event["org"] for app in visible_apps):
                result.append(event)
        elif event["type"] == "certificate_expiry":
            artifact = idx["artifacts"][event["artifact"]]
            if artifact["applies_to"]["products"] and any(
                p in visible_products for p in artifact["applies_to"]["products"]
            ):
                result.append(event)
        elif event.get("product") in visible_products:
            result.append(event)
    return result


def open_actions(data: dict, viewer: str, as_of) -> list[dict]:
    """未办结的补件/驳回/待办，标注责任人与期限，按到期日升序。"""
    today = parse_day(as_of)
    visible_ids = {app["id"] for app in visible_applications(data, viewer)}
    idx = build_index(data)
    rows = []
    for action in data["actions"]:
        if action["status"] != "open" or action["application"] not in visible_ids:
            continue
        due = parse_day(action["due_on"])
        days_left = (due - today).days
        rows.append({
            **action,
            "kind_name": ACTION_KIND_NAMES[action["kind"]],
            "application_name": _application_label(idx, action["application"]),
            "owner_org_name": org_name(idx, action["owner"]["org"]),
            "days_left": days_left,
            "overdue": days_left < 0,
        })
    rows.sort(key=lambda a: (a["due_on"], a["id"]))
    return rows


def stale_filings(data: dict, viewer: str, as_of) -> list[dict]:
    """仍在接洽/申报阶段、卷宗却钉住旧版资料的条目（旧版资料被拿去申报的风险）。"""
    idx = build_index(data)
    rows = []
    for app in visible_applications(data, viewer):
        if app["stage"] not in ("lead", "filing"):
            continue
        for entry in app["dossier"]:
            artifact = idx["artifacts"][entry["artifact"]]
            current = current_version(artifact)
            if entry["version"] != current["version"]:
                rows.append({
                    "application": app["id"],
                    "application_name": _application_label(idx, app["id"]),
                    "artifact": artifact["id"],
                    "artifact_title": artifact["title"],
                    "pinned": entry["version"],
                    "current": current["version"],
                    "note": f"卷宗钉住的《{artifact['title']}》为 {entry['version']}，"
                            f"当前有效版本为 {current['version']}，请替换后再申报",
                })
    return rows


def expiring_artifacts(data: dict, viewer: str, as_of, window: int = EXPIRY_WARNING_DAYS) -> list[dict]:
    """当前版本在 window 天内到期的资料，并找出卷宗引用它们的可见申请。"""
    idx = build_index(data)
    today = parse_day(as_of)
    visible_app_ids = {app["id"] for app in visible_applications(data, viewer)}
    rows = []
    for artifact in visible_artifacts(data, viewer):
        current = current_version(artifact)
        valid_until = current.get("valid_until")
        if not valid_until:
            continue
        days_left = (parse_day(valid_until) - today).days
        if days_left > window:
            continue
        affected = [
            app["id"]
            for app in idx["applications"].values()
            if app["id"] in visible_app_ids
            and any(e["artifact"] == artifact["id"] for e in app["dossier"])
        ]
        rows.append({
            "artifact": artifact["id"],
            "title": artifact["title"],
            "type": artifact["type"],
            "version": current["version"],
            "valid_until": valid_until,
            "days_left": days_left,
            "expired": days_left < 0,
            "affected_applications": affected,
        })
    rows.sort(key=lambda r: (r["valid_until"], r["artifact"]))
    return rows


def event_impact(data: dict, event: dict, as_of) -> dict:
    """单个变更事件波及哪些申请，以及原因。"""
    idx = build_index(data)
    today = parse_day(as_of)
    affected: dict[str, list[str]] = {}
    notes: list[str] = []

    def add(app_id: str, reason: str) -> None:
        affected.setdefault(app_id, []).append(reason)

    if event["type"] == "certificate_expiry":
        artifact = idx["artifacts"][event["artifact"]]
        current = current_version(artifact)
        valid_until = current.get("valid_until")
        days_left = (parse_day(valid_until) - today).days if valid_until else None
        for app in idx["applications"].values():
            if any(e["artifact"] == artifact["id"] for e in app["dossier"]):
                remain = f"，剩余 {days_left} 天" if days_left is not None and days_left >= 0 else "，已过期"
                add(app["id"],
                    f"卷宗引用《{artifact['title']}》{current['version']}，"
                    f"有效期至 {valid_until}{remain}，需启动续期并更新卷宗")
    elif event["type"] == "indication_change":
        product = idx["products"][event["product"]]
        for app in idx["applications"].values():
            if app["product"] != product["id"]:
                continue
            if app["stage"] == "approved":
                add(app["id"], "已获批适应症不含本次调整，需评估变更注册后方可宣称新适应症")
            elif app["stage"] == "filing":
                add(app["id"], "审评中的申报需评估是否补充新适应症资料或变更受理内容")
            elif app["stage"] == "lead":
                add(app["id"], "申报策略应按新适应症调整，临床与标签资料同步更新")
            else:
                add(app["id"], "上市后宣传与说明书需与新适应症范围核对")
    elif event["type"] == "site_change":
        product = idx["products"][event["product"]]
        for app in idx["applications"].values():
            if app["product"] == product["id"]:
                add(app["id"],
                    "生产场地变化，需办理许可事项变更/备案，并确认体系证书覆盖新场地")
    elif event["type"] == "agent_termination":
        agent = event["org"]
        for app in idx["applications"].values():
            if app.get("agent_org") == agent:
                add(app["id"],
                    f"本地代理《{org_name(idx, agent)}》已终止，"
                    f"需在 {NEW_AGENT_GRACE_DAYS} 日内指定新代理并办理变更，"
                    "否则注册证维持与集采资格受影响")
        revoked = [g for g in data["authorizations"] if g["org"] == agent and g["status"] == "revoked"]
        for grant in revoked:
            notes.append(f"授权已收回：《{idx['artifacts'][grant['artifact']]['title']}》（{grant['revoked_on']}）")
        affected_countries = {
            idx["applications"][app_id]["country"] for app_id in affected
        }
        for artifact in idx["artifacts"].values():
            if artifact["type"] == "procurement" and any(
                c in affected_countries for c in artifact["applies_to"]["countries"]
            ):
                notes.append(f"集采机会《{artifact['title']}》要求有效本地代理，需在新代理到位后申报")

    return {
        "event": event,
        "type_name": EVENT_TYPE_NAMES[event["type"]],
        "affected": [
            {"application": app_id, "application_name": _application_label(idx, app_id), "reasons": reasons}
            for app_id, reasons in sorted(affected.items())
        ],
        "notes": notes,
    }


def all_impacts(data: dict, viewer: str, as_of) -> list[dict]:
    """全部变更事件的影响分析，按查看者可见范围过滤。"""
    visible_ids = {app["id"] for app in visible_applications(data, viewer)}
    impacts = []
    for event in _visible_events(data, viewer):
        impact = event_impact(data, event, as_of)
        impact["affected"] = [a for a in impact["affected"] if a["application"] in visible_ids]
        impacts.append(impact)
    return impacts


def decision_audit(data: dict, viewer: str, as_of) -> list[dict]:
    """核对每个准入判断钉住的证据版本。

    证据状态：ok（仍为当前版本）、superseded（判断后又出新版）、
    stale_at_decision（判断时已有更新版本）、expired（判断时该版本已过期）。
    """
    idx = build_index(data)
    rows = []
    for decision in _visible_decisions(data, viewer):
        decided_on = parse_day(decision["decided_on"])
        entries = []
        worst = "ok"
        rank = {"ok": 0, "superseded": 1, "stale_at_decision": 2, "expired": 2}
        for evidence in decision["evidence"]:
            artifact = idx["artifacts"][evidence["artifact"]]
            pinned = version_of(artifact, evidence["version"])
            newer = [v for v in artifact["versions"] if v["issued_on"] > pinned["issued_on"]]
            status = "ok"
            if pinned.get("valid_until") and parse_day(pinned["valid_until"]) < decided_on:
                status = "expired"
            elif any(v["issued_on"] <= decision["decided_on"] for v in newer):
                status = "stale_at_decision"
            elif newer:
                status = "superseded"
            if rank[status] > rank[worst]:
                worst = status
            entries.append({
                "artifact": artifact["id"],
                "artifact_title": artifact["title"],
                "pinned": evidence["version"],
                "current": current_version(artifact)["version"],
                "status": status,
            })
        rows.append({
            "decision": decision["id"],
            "application": decision["application"],
            "application_name": _application_label(idx, decision["application"]),
            "kind": decision["kind"],
            "decided_on": decision["decided_on"],
            "decided_by": org_name(idx, decision["decided_by"]),
            "outcome": decision["outcome"],
            "evidence": entries,
            "worst": worst,
        })
    rows.sort(key=lambda r: (r["decided_on"], r["decision"]))
    return rows


def next_actions(data: dict, app: dict, as_of) -> list[dict]:
    """按优先级给出该申请的下一步行动。"""
    idx = build_index(data)
    today = parse_day(as_of)
    items: list[dict] = []

    def add(priority: int, kind: str, text: str, owner: str = "", due_on: str = "") -> None:
        items.append({"priority": priority, "kind": kind, "text": text, "owner": owner, "due_on": due_on})

    viewer = _product_owner(idx, app["product"])
    for action in open_actions(data, viewer, today):
        if action["application"] != app["id"]:
            continue
        owner = f"{action['owner_org_name']}·{action['owner']['person']}"
        if action["overdue"]:
            add(0, action["kind"],
                f"【逾期 {-action['days_left']} 天】{action['kind_name']}：{action['title']}",
                owner, action["due_on"])
        else:
            add(2, action["kind"],
                f"{action['kind_name']}：{action['title']}（剩余 {action['days_left']} 天）",
                owner, action["due_on"])

    for stale in stale_filings(data, viewer, today):
        if stale["application"] == app["id"]:
            add(1, "stale", stale["note"], "企业注册负责人")

    for impact in all_impacts(data, viewer, today):
        for hit in impact["affected"]:
            if hit["application"] != app["id"]:
                continue
            for reason in hit["reasons"]:
                priority = 1 if impact["event"]["type"] == "agent_termination" else 2
                add(priority, impact["event"]["type"], f"[{impact['type_name']}] {reason}")
        for note in impact["notes"]:
            if any(h["application"] == app["id"] for h in impact["affected"]):
                add(2, impact["event"]["type"], f"[{impact['type_name']}] {note}")

    for artifact in visible_artifacts(data, viewer):
        if artifact["type"] != "procurement":
            continue
        scope = artifact["applies_to"]
        if app["product"] not in scope["products"] or app["country"] not in scope["countries"]:
            continue
        if app["stage"] not in ("approved", "in_use"):
            continue
        current = current_version(artifact)
        if current.get("valid_until") and parse_day(current["valid_until"]) >= today:
            add(3, "procurement",
                f"集采机会：《{artifact['title']}》，申报窗口至 {current['valid_until']}",
                "企业商务负责人", current["valid_until"])

    if not items:
        defaults = {
            "lead": "完成分类与路径差距分析，备齐资料后启动正式申报",
            "filing": "跟进审评进度，及时响应补件要求",
            "approved": "维护证书有效性，关注集采机会与变更义务",
            "in_use": "开展上市后监测，按周期准备续证",
        }
        add(4, "stage", defaults[app["stage"]])

    items.sort(key=lambda i: (i["priority"], i["due_on"] or "9999-12-31"))
    return items


def application_card(data: dict, app: dict, as_of) -> dict:
    """单个申请在工作台上的完整卡片。"""
    idx = build_index(data)
    product = idx["products"][app["product"]]
    country = idx["countries"][app["country"]]
    path = idx["paths"][app["path"]]
    owner = _product_owner(idx, app["product"])

    dossier = []
    for entry in app["dossier"]:
        artifact = idx["artifacts"][entry["artifact"]]
        current = current_version(artifact)
        pinned = version_of(artifact, entry["version"])
        dossier.append({
            "artifact": artifact["id"],
            "title": artifact["title"],
            "type": artifact["type"],
            "pinned": entry["version"],
            "current": current["version"],
            "superseded": entry["version"] != current["version"],
            "valid_until": (pinned or {}).get("valid_until"),
        })

    return {
        "id": app["id"],
        "product_name": f"{product['name']}（{product['model']}）",
        "owner_org": org_name(idx, owner),
        "country": country["name"],
        "stage": app["stage"],
        "stage_name": STAGE_NAMES[app["stage"]],
        "path": {
            "classification": path["classification"],
            "route": path["route"],
            "regulations": [
                {"citation": idx["regulations"][r]["citation"],
                 "source_url": idx["regulations"][r].get("source_url", "")}
                for r in path["regulation_refs"]
            ],
        },
        "label_language": country["label_language"],
        "agent": org_name(idx, app["agent_org"]) if app.get("agent_org") else "（未指定）",
        "dossier": dossier,
        "open_actions": [a for a in open_actions(data, owner, as_of) if a["application"] == app["id"]],
        "next_actions": next_actions(data, app, as_of)[:5],
        "impacts": [
            {"event": impact["event"]["id"], "type_name": impact["type_name"], "reasons": hit["reasons"]}
            for impact in all_impacts(data, owner, as_of)
            for hit in impact["affected"]
            if hit["application"] == app["id"]
        ],
        "decisions": [d for d in decision_audit(data, owner, as_of) if d["application"] == app["id"]],
    }


def workbench_view(data: dict, viewer: str, as_of) -> dict:
    """统一工作台视图：四阶段分列、待办、影响、到期、稽核，全部按查看者过滤。"""
    idx = build_index(data)
    org = _require_viewer(idx, viewer)
    today = parse_day(as_of)
    apps = visible_applications(data, viewer)
    stages = []
    for stage_id in STAGE_ORDER:
        stage = idx["stages"][stage_id]
        cards = [application_card(data, app, today) for app in apps if app["stage"] == stage_id]
        cards.sort(key=lambda c: c["id"])
        stages.append({
            "id": stage_id,
            "name": stage["name"],
            "description": stage["description"],
            "applications": cards,
        })
    return {
        "viewer": {"id": org["id"], "name": org["name"], "type": org["type"]},
        "as_of": today.isoformat(),
        "stages": stages,
        "open_actions": open_actions(data, viewer, today),
        "stale": stale_filings(data, viewer, today),
        "expiring": expiring_artifacts(data, viewer, today),
        "impacts": all_impacts(data, viewer, today),
        "audit": decision_audit(data, viewer, today),
    }


def _application_label(idx: dict, app_id: str) -> str:
    app = idx["applications"][app_id]
    product = idx["products"][app["product"]]
    country = idx["countries"][app["country"]]
    return f"{product['name']}·{country['name']}"
