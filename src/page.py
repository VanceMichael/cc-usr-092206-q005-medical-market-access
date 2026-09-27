"""把统一工作台视图渲染成自包含的 HTML 页面。

页面按初步接洽、正式申报、获批上市、实际使用四阶段分列，
并给出补件/驳回、变更影响、到期提醒、旧版申报风险与准入判断稽核面板。
"""

from html import escape

STATUS_NAMES = {
    "ok": "与当前版本一致",
    "superseded": "判断后证据已更新",
    "stale_at_decision": "判断时已有更新版本",
    "expired": "判断时版本已过期",
}

CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; font-family: "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
       background: #f4f6f8; color: #1f2933; }
header { background: #123a5c; color: #fff; padding: 18px 28px; }
header h1 { margin: 0 0 6px; font-size: 20px; }
header .meta { font-size: 13px; opacity: .85; }
main { padding: 20px 28px 40px; }
.summary { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.summary .chip { background: #fff; border: 1px solid #dde3ea; border-radius: 8px;
                 padding: 10px 16px; font-size: 13px; }
.summary .chip b { display: block; font-size: 20px; margin-top: 2px; }
.summary .chip.warn b { color: #b45309; }
.summary .chip.bad b { color: #b91c1c; }
.pipeline { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; align-items: start; }
.stage { background: #eef2f6; border-radius: 10px; padding: 10px; }
.stage > h2 { font-size: 15px; margin: 2px 4px 2px; }
.stage > p.desc { font-size: 12px; color: #52606d; margin: 0 4px 10px; }
.card { background: #fff; border: 1px solid #dde3ea; border-radius: 8px;
        padding: 12px 14px; margin-bottom: 12px; font-size: 13px; }
.card h3 { font-size: 14px; margin: 0 0 6px; }
.card .row { margin: 3px 0; }
.card .k { color: #52606d; }
.card ul, .card ol { margin: 4px 0 4px 18px; padding: 0; }
.card li { margin: 3px 0; }
table { border-collapse: collapse; width: 100%; font-size: 12.5px; }
th, td { border: 1px solid #e4e9ef; padding: 4px 8px; text-align: left; vertical-align: top; }
th { background: #f0f4f8; }
.badge { display: inline-block; border-radius: 999px; padding: 1px 9px;
         font-size: 11.5px; line-height: 18px; white-space: nowrap; }
.b-ok { background: #e3f2e9; color: #1d7a46; }
.b-warn { background: #fdf0d5; color: #b45309; }
.b-bad { background: #fde2e1; color: #b91c1c; }
.b-info { background: #e0ecfb; color: #1d4ed8; }
.b-stage { background: #123a5c; color: #fff; }
.panels { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-top: 18px; }
.panel { background: #fff; border: 1px solid #dde3ea; border-radius: 10px; padding: 14px 16px; }
.panel h2 { font-size: 15px; margin: 0 0 10px; }
.panel .item { border-top: 1px dashed #e4e9ef; padding: 8px 0; font-size: 13px; }
.panel .item:first-of-type { border-top: 0; }
.muted { color: #7b8794; }
a { color: #1d4ed8; }
footer { padding: 12px 28px 24px; font-size: 12px; color: #7b8794; }
"""


def _badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{escape(text)}</span>'


def _version_badge(entry: dict) -> str:
    if entry["superseded"]:
        return _badge(f"钉住 {entry['pinned']}（旧版，当前 {entry['current']}）", "b-bad")
    return _badge(f"钉住 {entry['pinned']}（当前版本）", "b-ok")


def _action_badge(action: dict) -> str:
    if action["overdue"]:
        return _badge(f"逾期 {-action['days_left']} 天", "b-bad")
    return _badge(f"剩余 {action['days_left']} 天", "b-warn" if action["days_left"] <= 14 else "b-info")


def _audit_badge(status: str) -> str:
    cls = {"ok": "b-ok", "superseded": "b-warn", "stale_at_decision": "b-bad", "expired": "b-bad"}[status]
    return _badge(STATUS_NAMES[status], cls)


def _render_card(card: dict) -> str:
    parts = ['<div class="card">']
    parts.append(f"<h3>{escape(card['product_name'])}</h3>")
    parts.append(
        f'<div class="row">{_badge(card["stage_name"], "b-stage")} '
        f'{_badge(card["country"], "b-info")}</div>'
    )
    parts.append(f'<div class="row"><span class="k">持有企业：</span>{escape(card["owner_org"])}</div>')
    parts.append(
        f'<div class="row"><span class="k">注册路径：</span>{escape(card["path"]["classification"])}；'
        f'{escape(card["path"]["route"])}</div>'
    )
    regs = "；".join(
        f'<a href="{escape(r["source_url"])}">{escape(r["citation"])}</a>' if r["source_url"]
        else escape(r["citation"])
        for r in card["path"]["regulations"]
    )
    parts.append(f'<div class="row"><span class="k">法规来源：</span>{regs}</div>')
    parts.append(
        f'<div class="row"><span class="k">标签语言：</span>{escape(card["label_language"])}；'
        f'<span class="k">本地代理：</span>{escape(card["agent"])}</div>'
    )
    if card["dossier"]:
        rows = "".join(
            f"<tr><td>{escape(d['title'])}</td><td>{_version_badge(d)}</td>"
            f"<td>{escape(d['valid_until'] or '—')}</td></tr>"
            for d in card["dossier"]
        )
        parts.append(
            '<div class="row"><span class="k">申报卷宗：</span></div>'
            f"<table><tr><th>资料</th><th>版本</th><th>有效期至</th></tr>{rows}</table>"
        )
    if card["open_actions"]:
        items = "".join(
            f"<li>{_action_badge(a)} {escape(a['kind_name'])}：{escape(a['title'])}"
            f"<br><span class='muted'>责任人：{escape(a['owner_org_name'])}·{escape(a['owner']['person'])}；"
            f"期限 {escape(a['due_on'])}</span></li>"
            for a in card["open_actions"]
        )
        parts.append(f'<div class="row"><span class="k">补件/驳回：</span></div><ul>{items}</ul>')
    if card["impacts"]:
        items = "".join(
            f"<li>{_badge(i['type_name'], 'b-warn')} {escape(reason)}</li>"
            for i in card["impacts"]
            for reason in i["reasons"]
        )
        parts.append(f'<div class="row"><span class="k">变更影响：</span></div><ul>{items}</ul>')
    if card["next_actions"]:
        items = "".join(
            f"<li>{escape(a['text'])}"
            + (f"<br><span class='muted'>责任：{escape(a['owner'])}；期限 {escape(a['due_on'])}</span>"
               if a["owner"] else "")
            + "</li>"
            for a in card["next_actions"]
        )
        parts.append(f'<div class="row"><span class="k">下一步行动：</span></div><ol>{items}</ol>')
    if card["decisions"]:
        items = "".join(
            f"<li>{escape(d['kind'])}（{escape(d['decided_on'])}，{escape(d['decided_by'])}）："
            + "、".join(f"{escape(e['artifact_title'])} {escape(e['pinned'])}" for e in d["evidence"])
            + f" {_audit_badge(d['worst'])}</li>"
            for d in card["decisions"]
        )
        parts.append(f'<div class="row"><span class="k">准入判断记录：</span></div><ul>{items}</ul>')
    parts.append("</div>")
    return "".join(parts)


def _render_actions_panel(actions: list) -> str:
    if not actions:
        return "<p class='muted'>当前没有未办结的补件或驳回。</p>"
    rows = "".join(
        f"<tr><td>{escape(a['kind_name'])}</td><td>{escape(a['application_name'])}</td>"
        f"<td>{escape(a['title'])}</td>"
        f"<td>{escape(a['owner_org_name'])}·{escape(a['owner']['person'])}</td>"
        f"<td>{escape(a['due_on'])}</td><td>{_action_badge(a)}</td></tr>"
        for a in actions
    )
    return (
        "<table><tr><th>类型</th><th>申请</th><th>事项</th><th>责任人</th><th>期限</th><th>状态</th></tr>"
        f"{rows}</table>"
    )


def _render_impacts_panel(impacts: list) -> str:
    items = []
    for impact in impacts:
        event = impact["event"]
        affected = "".join(
            f"<li>{escape(a['application_name'])}<ul>"
            + "".join(f"<li>{escape(r)}</li>" for r in a["reasons"])
            + "</ul></li>"
            for a in impact["affected"]
        )
        notes = "".join(f"<li>{escape(n)}</li>" for n in impact["notes"])
        items.append(
            f'<div class="item">{_badge(impact["type_name"], "b-warn")} '
            f"<b>{escape(event['summary'])}</b> "
            f"<span class='muted'>{escape(event['occurred_on'])}</span>"
            f"<ul>{affected}{notes}</ul></div>"
        )
    return "".join(items) or "<p class='muted'>暂无变更事件。</p>"


def _render_audit_panel(audit: list) -> str:
    items = []
    for row in audit:
        evidence = "、".join(
            f"{escape(e['artifact_title'])} {escape(e['pinned'])}（{_audit_badge(e['status'])}）"
            for e in row["evidence"]
        )
        items.append(
            f'<div class="item"><b>{escape(row["kind"])}</b>·{escape(row["application_name"])}'
            f"<br><span class='muted'>{escape(row['decided_on'])} 由 {escape(row['decided_by'])} 作出："
            f"{escape(row['outcome'])}</span><br>证据版本：{evidence}</div>"
        )
    return "".join(items) or "<p class='muted'>暂无准入判断记录。</p>"


def _render_expiring_panel(expiring: list, stale: list) -> str:
    parts = []
    if expiring:
        items = []
        for e in expiring:
            if e["expired"]:
                badge = _badge("已过期", "b-bad")
            else:
                badge = _badge(f"剩余 {e['days_left']} 天", "b-warn")
            hit = (f"<br><span class='muted'>波及申请：{escape('、'.join(e['affected_applications']))}</span>"
                   if e["affected_applications"] else "")
            items.append(
                f'<div class="item">{badge} '
                f"《{escape(e['title'])}》{escape(e['version'])} 有效期至 {escape(e['valid_until'])}"
                f"{hit}</div>"
            )
        parts.append(f"<h3>到期提醒</h3>{''.join(items)}")
    if stale:
        items = "".join(
            f'<div class="item">{_badge("旧版风险", "b-bad")} {escape(s["application_name"])}：{escape(s["note"])}</div>'
            for s in stale
        )
        parts.append(f"<h3>旧版申报风险</h3>{items}")
    return "".join(parts) or "<p class='muted'>暂无到期资料或旧版申报风险。</p>"


def render_workbench_html(view: dict) -> str:
    """渲染完整的工作台页面。"""
    open_actions = view["open_actions"]
    overdue = sum(1 for a in open_actions if a["overdue"])
    total_apps = sum(len(s["applications"]) for s in view["stages"])
    summary = (
        f'<div class="chip">可见申请<b>{total_apps}</b></div>'
        f'<div class="chip">未办结事项<b>{len(open_actions)}</b></div>'
        f'<div class="chip {"bad" if overdue else ""}">已逾期<b>{overdue}</b></div>'
        f'<div class="chip">变更事件<b>{len(view["impacts"])}</b></div>'
        f'<div class="chip {"warn" if view["expiring"] else ""}">到期资料<b>{len(view["expiring"])}</b></div>'
        f'<div class="chip {"bad" if view["stale"] else ""}">旧版申报风险<b>{len(view["stale"])}</b></div>'
    )
    columns = []
    for stage in view["stages"]:
        cards = "".join(_render_card(c) for c in stage["applications"]) or "<p class='muted'>暂无申请</p>"
        columns.append(
            f'<section class="stage"><h2>{escape(stage["name"])}（{len(stage["applications"])}）</h2>'
            f'<p class="desc">{escape(stage["description"])}</p>{cards}</section>'
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>创新药械东盟准入统一工作台</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>创新药械东盟准入统一工作台</h1>
  <div class="meta">查看者：{escape(view["viewer"]["name"])}　数据日期：{escape(view["as_of"])}
  阶段：初步接洽 → 正式申报 → 获批上市 → 实际使用</div>
</header>
<main>
  <div class="summary">{summary}</div>
  <div class="pipeline">{"".join(columns)}</div>
  <div class="panels">
    <section class="panel"><h2>补件与驳回（责任人 · 期限）</h2>{_render_actions_panel(open_actions)}</section>
    <section class="panel"><h2>变更影响分析</h2>{_render_impacts_panel(view["impacts"])}</section>
    <section class="panel"><h2>准入判断证据稽核</h2>{_render_audit_panel(view["audit"])}</section>
    <section class="panel"><h2>到期与旧版风险</h2>{_render_expiring_panel(view["expiring"], view["stale"])}</section>
  </div>
</main>
<footer>未经授权的企业资料互相不可见；本页面内容已按查看者权限过滤。</footer>
</body>
</html>
"""
