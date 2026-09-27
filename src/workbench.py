"""统一工作台页面：四阶段看板、任务、变更影响、证据版本与审计日志。

以无依赖的 HTML 渲染，便于直接打开核对。命令行：

    python -m src.workbench                 # 服务机构全量视图（含演示时间线）
    python -m src.workbench --as ENT-1      # 企业视图
    python -m src.workbench --as P-OLD      # 旧合作方视图（只见被授权资料）
    python -m src.workbench --out page.html
"""

from __future__ import annotations

import argparse
import html
from datetime import date

from .models import (
    STAGE_ORDER,
    Actor,
    ChangeEvent,
    ChangeKind,
    Stage,
    VersionStatus,
)
from .seed import TODAY, build
from .services import FilingError, Workbench

STAGE_COLORS = {
    Stage.INITIAL_CONTACT: "#8a6d2b",
    Stage.FORMAL_SUBMISSION: "#1f5fa8",
    Stage.APPROVED: "#1f7a4d",
    Stage.IN_USE: "#5b3a8c",
}


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def run_demo_timeline(wb: Workbench) -> list[str]:
    """演练：旧版拦截、印尼正式申报，以及四类变更的自动影响分析。"""

    notes: list[str] = []

    # 合作方用旧版 VER-101 拼印尼申报包：版本与适用范围双重不合规
    stale_package = ("VER-101", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601")
    try:
        wb.submit_filing("APP-ID", stale_package, TODAY, by="旧版资料合作方")
    except FilingError as exc:
        notes.append("旧版/跨范围申报已被拦截：" + "；".join(exc.problems))

    # 企业按现行版本、正确适用范围正式提交印尼申请
    good_package = ("VER-111", "VER-202", "VER-303", "VER-402", "VER-501", "VER-601")
    wb.submit_filing("APP-ID", good_package, TODAY, by="陈项目经理（服务机构）")
    notes.append("印尼申请已按现行证据版本正式申报")

    # 越南已获批并完成医保挂网，转入实际使用阶段
    wb.start_use("APP-VN", "王准入（企业RA）", date(2026, 10, 8))
    notes.append("越南路径获批后已挂网，进入实际使用阶段")

    # 四类变更事件
    changes = (
        ChangeEvent(
            kind=ChangeKind.CERTIFICATE_EXPIRED,
            occurred_on=date(2026, 10, 21),
            note="印尼注册证书到期未换发",
            item_id="EV-CERT-ID",
        ),
        ChangeEvent(
            kind=ChangeKind.INDICATION_ADJUSTED,
            occurred_on=date(2026, 11, 2),
            note="适应症扩展至冠脉血管介入导航",
            product_id="P1",
        ),
        ChangeEvent(
            kind=ChangeKind.SITE_CHANGED,
            occurred_on=date(2026, 11, 5),
            note="生产场地迁至广西南宁二号场地",
            product_id="P1",
        ),
        ChangeEvent(
            kind=ChangeKind.AGENT_TERMINATED,
            occurred_on=date(2026, 11, 10),
            note="曼谷本地注册代理终止合作",
            agent_id="P-TH",
        ),
    )
    labels = {
        ChangeKind.CERTIFICATE_EXPIRED: "证书到期：自动定位持证申报并生成续期任务",
        ChangeKind.INDICATION_ADJUSTED: "适应症调整：全部在审/已上市路径自动生成变更申报任务",
        ChangeKind.SITE_CHANGED: "生产场地变化：自动比对受影响国家路径",
        ChangeKind.AGENT_TERMINATED: "代理终止：自动解除泰国路径授权并要求重新指定代理",
    }
    for event in changes:
        wb.apply_change(event)
        notes.append(labels[event.kind])
    return notes


# ---------------------------------------------------------------------- 渲染


def stage_stepper(current: Stage) -> str:
    cells = []
    for stage in STAGE_ORDER:
        idx = STAGE_ORDER.index(stage)
        cur_idx = STAGE_ORDER.index(current)
        if idx < cur_idx:
            cls, color = "done", STAGE_COLORS[stage]
        elif idx == cur_idx:
            cls, color = "current", STAGE_COLORS[stage]
        else:
            cls, color = "todo", "#9aa3ad"
        cells.append(
            f'<span class="step {cls}" style="--c:{color}">{esc(stage.value)}</span>'
        )
    return '<div class="stepper">' + "".join(cells) + "</div>"


def render_application_card(wb: Workbench, app, today: date) -> str:
    path = wb.path_of(app)
    product = wb.product_of(app)
    parts = [
        f'<section class="card" style="--accent:{STAGE_COLORS[app.stage]}">',
        f'<h3>{esc(path.country)} · {esc(product.name)}</h3>',
        stage_stepper(app.stage),
        '<dl class="facts">',
        f"<dt>产品分类</dt><dd>{esc(path.product_class)}</dd>",
        f"<dt>标签语言</dt><dd>{esc(path.label_language)}</dd>",
        f"<dt>本地代理</dt><dd>{esc(wb.actors[path.agent_id].name if path.agent_id else '未指定（授权链中断）')}</dd>",
        f"<dt>医保采购</dt><dd>{esc(path.procurement_channel or '暂无通道')}</dd>",
        f"<dt>法规来源</dt><dd class=src>{esc(path.regulatory_source)}</dd>",
        "</dl>",
    ]

    tasks = wb.open_tasks(app.application_id)
    if tasks:
        parts.append('<ul class="tasks">')
        for task in tasks:
            overdue = task.is_overdue(today)
            badge = "逾期" if overdue else "期限 " + task.due_on.isoformat()
            parts.append(
                "<li" + (' class="overdue"' if overdue else "") + ">"
                f"<b>{esc(task.kind.value)}</b> {esc(task.title)}"
                f'<span class="owner">责任人 {esc(task.assignee)}</span>'
                f'<span class="due">{esc(badge)}</span></li>'
            )
        parts.append("</ul>")

    actions = wb.next_actions(app, today)
    parts.append('<div class="next"><b>下一步行动</b><ul>')
    for action in actions:
        parts.append(f"<li>{esc(action)}</li>")
    parts.append("</ul></div>")
    parts.append("</section>")
    return "".join(parts)


def render_evidence_audit(wb: Workbench, today: date, viewer: Actor) -> str:
    visible_apps = {a.application_id for a in wb.visible_applications(viewer)}
    rows = []
    for decision in wb.decisions:
        if decision.application_id not in visible_apps:
            continue
        app = wb.applications[decision.application_id]
        path = wb.path_of(app)
        refs = []
        for item_id, version_id in decision.evidence_refs:
            item = wb.items[item_id]
            version = wb.get_version(version_id)
            current = wb.current_version(item_id, today)
            state = "现行" if current and current.version_id == version_id else "已更新"
            refs.append(
                f"{esc(item.title)}（v{version.version_no}，{esc(state)}）"
            )
        rows.append(
            "<tr>"
            f"<td>{esc(path.country)}</td>"
            f"<td>{esc(decision.outcome)}</td>"
            f"<td>{esc(decision.decided_by)}<br>{decision.decided_on}</td>"
            f"<td>{'；'.join(refs)}</td>"
            "</tr>"
        )
    return (
        '<table class="grid"><thead><tr><th>目标国</th><th>准入判断</th>'
        "<th>判断人/日期</th><th>采用的证据版本</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def render_library(wb: Workbench, viewer: Actor, today: date) -> str:
    rows = []
    for item in wb.visible_items(viewer):
        scope = "全部目标国" if not item.countries else "、".join(sorted(item.countries))
        current = wb.current_version(item.item_id, today)
        versions = sorted(wb.versions[item.item_id], key=lambda v: v.version_no)
        vtext = []
        for ver in versions:
            mark = {
                VersionStatus.CURRENT: "现行",
                VersionStatus.SUPERSEDED: "已替代",
                VersionStatus.EXPIRED: "已到期",
                VersionStatus.REVOKED: "已作废",
            }[ver.status]
            cur = current and current.version_id == ver.version_id
            vtext.append(
                f'<span class="ver{" cur" if cur else ""}">v{ver.version_no}·{mark}</span>'
            )
        shared = "、".join(
            wb.actors[a].name for a in sorted(item.shared_with) if a in wb.actors
        ) or "—"
        rows.append(
            "<tr>"
            f"<td>{esc(item.kind.value)}</td><td>{esc(item.title)}</td>"
            f"<td>{esc(scope)}</td><td class=vers>{''.join(vtext)}</td>"
            f"<td>{esc(shared)}</td></tr>"
        )
    return (
        '<table class="grid"><thead><tr><th>类型</th><th>资料</th>'
        "<th>适用范围</th><th>版本</th><th>授权可见的合作方</th>"
        f"</tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def render_impacts(wb: Workbench, viewer: Actor) -> str:
    visible_apps = {a.application_id for a in wb.visible_applications(viewer)}
    blocks = []
    for report in wb.impacts:
        event = report.event
        rows = []
        for impact in report.impacts:
            if impact.application_id not in visible_apps:
                continue
            app = wb.applications[impact.application_id]
            path = wb.path_of(app)
            task = wb.tasks[impact.task_id]
            rows.append(
                "<li>"
                f"<b>{esc(path.country)} · {esc(app.application_id)}</b>"
                f"（{esc(app.stage.value)}）— {esc(impact.reason)}"
                f'<div class="impact-task">→ 已生成任务：{esc(task.title)}；'
                f"责任人 {esc(task.assignee)}；期限 {task.due_on}</div>"
                "</li>"
            )
        if not rows:
            continue
        blocks.append(
            f'<details open><summary><span class="tag">{esc(event.kind.value)}</span>'
            f"{esc(event.note)} <time>{event.occurred_on}</time> · "
            f"本方相关申请 {len(rows)} 件</summary>"
            f'<ul class="impacts">{"".join(rows)}</ul></details>'
        )
    return "".join(blocks) or "<p>暂无与本方相关的变更事件。</p>"


def render_audit(wb: Workbench, viewer: Actor) -> str:
    visible_apps = {a.application_id for a in wb.visible_applications(viewer)}
    task_to_app = {t.task_id: t.application_id for t in wb.tasks.values()}
    is_admin = viewer.role.value == "区域服务机构"
    rows = []
    for e in wb.audit:
        if not is_admin and e.target not in visible_apps and task_to_app.get(e.target) not in visible_apps:
            continue
        rows.append(
            f"<tr><td>{e.on}</td><td>{esc(e.actor)}</td><td>{esc(e.action)}</td>"
            f"<td>{esc(e.target)}</td><td>{esc(e.detail)}</td></tr>"
        )
    return (
        '<table class="grid"><thead><tr><th>日期</th><th>操作人</th><th>动作</th>'
        f"<th>对象</th><th>说明</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"
    )


def render(wb: Workbench, viewer: Actor, today: date, notices: list[str]) -> str:
    grouped = wb.applications_by_stage(viewer)
    columns = []
    for stage in STAGE_ORDER:
        cards = "".join(render_application_card(wb, app, today) for app in grouped[stage])
        columns.append(
            f'<section class="column" style="--c:{STAGE_COLORS[stage]}">'
            f"<h2>{esc(stage.value)}<span>{len(grouped[stage])}</span></h2>"
            f"{cards}</section>"
        )

    notice_html = "".join(f"<li>{esc(n)}</li>" for n in notices)
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>东盟药械准入统一工作台</title>
<style>
:root {{ --bg:#f4f5f7; --ink:#1d2430; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"PingFang SC","Microsoft YaHei",sans-serif; background:var(--bg); color:var(--ink); }}
header {{ padding:20px 28px; background:#10243d; color:#fff; }}
header h1 {{ margin:0 0 6px; font-size:20px; }}
header .meta {{ font-size:13px; opacity:.82; }}
.notices {{ margin:16px 28px 0; padding:12px 18px; background:#fff7e6; border:1px solid #e6c178; border-radius:8px; }}
.notices li {{ margin:3px 0; }}
main {{ padding:18px 28px 40px; }}
.board {{ display:grid; grid-template-columns:repeat(4,1fr); gap:14px; }}
.column h2 {{ font-size:14px; color:var(--c); border-bottom:2px solid var(--c); padding-bottom:6px; display:flex; justify-content:space-between; }}
.column h2 span {{ background:var(--c); color:#fff; border-radius:10px; padding:0 9px; }}
.card {{ background:#fff; border-radius:10px; padding:14px; margin-bottom:12px; border-left:4px solid var(--accent); box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.card h3 {{ margin:0 0 10px; font-size:14px; }}
.stepper {{ display:flex; font-size:11px; margin-bottom:10px; }}
.step {{ flex:1; text-align:center; padding:4px 2px; color:#fff; background:#c6ccd3; }}
.step:first-child {{ border-radius:6px 0 0 6px; }} .step:last-child {{ border-radius:0 6px 6px 0; }}
.step.done {{ background:color-mix(in srgb, var(--c) 45%, #fff); }}
.step.current {{ background:var(--c); font-weight:700; outline:2px solid color-mix(in srgb, var(--c) 35%, #fff); }}
dl.facts {{ margin:0; font-size:12px; }}
dl.facts dt {{ color:#67707c; margin-top:6px; }}
dl.facts dd {{ margin:1px 0 0; }} dd.src {{ color:#445063; }}
ul.tasks {{ list-style:none; padding:0; margin:10px 0; font-size:12px; }}
ul.tasks li {{ background:#fdf3f2; border:1px solid #e7c4c0; border-radius:6px; padding:6px 8px; margin:5px 0; }}
ul.tasks li.overdue {{ border-color:#c0392b; background:#fdecea; }}
.owner {{ display:block; color:#5a6472; }} .due {{ float:right; font-weight:700; color:#c0392b; }}
.next {{ font-size:12px; background:#f0f5fb; border-radius:6px; padding:7px 10px; }}
.next ul {{ margin:5px 0 0; padding-left:18px; }}
section.panel {{ margin-top:26px; }}
section.panel h2 {{ font-size:16px; border-left:4px solid #10243d; padding-left:9px; }}
table.grid {{ width:100%; border-collapse:collapse; background:#fff; font-size:12.5px; border-radius:8px; overflow:hidden; }}
table.grid th, table.grid td {{ border:1px solid #e3e6ea; padding:7px 9px; text-align:left; vertical-align:top; }}
table.grid th {{ background:#eef1f5; }}
.ver {{ display:inline-block; background:#eceff3; border-radius:4px; padding:1px 6px; margin:1px 2px; font-size:11px; }}
.ver.cur {{ background:#d8f0e3; color:#176d3f; font-weight:700; }}
details {{ background:#fff; border:1px solid #dfe3e8; border-radius:8px; padding:10px 14px; margin:8px 0; }}
summary {{ cursor:pointer; font-size:13.5px; }} summary time {{ color:#74808f; font-size:12px; }}
.tag {{ background:#8c4a1f; color:#fff; border-radius:4px; padding:1px 7px; font-size:11px; margin-right:7px; }}
ul.impacts {{ font-size:12.5px; }} .impact-task {{ color:#445063; margin:2px 0 6px 14px; }}
</style></head>
<body>
<header>
  <h1>创新药械东盟准入统一工作台</h1>
  <div class="meta">广西区域服务机构 ｜ 当前视图：{esc(viewer.name)}（{esc(viewer.role.value)}）｜ 数据截至 {today}</div>
</header>
<div class="notices"><ul>{notice_html}</ul></div>
<main>
  <div class="board">{''.join(columns)}</div>
  <section class="panel"><h2>变更影响联动（证书到期 / 适应症 / 生产场地 / 代理终止）</h2>{render_impacts(wb, viewer)}</section>
  <section class="panel"><h2>准入判断证据核对</h2>{render_evidence_audit(wb, today, viewer)}</section>
  <section class="panel"><h2>资料库（按适用范围与授权隔离）</h2>{render_library(wb, viewer, today)}</section>
  <section class="panel"><h2>操作审计</h2>{render_audit(wb, viewer)}</section>
</main>
</body></html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成东盟准入工作台页面")
    parser.add_argument("--as", dest="actor", default="ORG-1", help="观察者 ID")
    parser.add_argument("--out", help="输出 HTML 路径；缺省输出到 stdout")
    parser.add_argument("--date", default="2026-11-15", help="页面数据截止日期")
    args = parser.parse_args()

    wb = build()
    viewer = wb.actors[args.actor]
    timeline = run_demo_timeline(wb)
    if args.actor == "ORG-1":
        notices = timeline
    else:
        notices = ["当前为受限视图：仅显示本企业资料或明确授权给本方的资料，其他企业资料不可见。"]
    page = render(wb, viewer, date.fromisoformat(args.date), notices)
    if args.out:
        from pathlib import Path

        Path(args.out).write_text(page, encoding="utf-8")
        print(f"已生成 {args.out}")
    else:
        print(page)


if __name__ == "__main__":
    main()
