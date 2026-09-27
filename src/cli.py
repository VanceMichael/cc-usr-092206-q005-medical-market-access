"""统一准入工作台命令行入口。

用法示例：
    python -m src.cli workbench --viewer org-gx
    python -m src.cli actions --viewer org-a
    python -m src.cli impacts --viewer org-gx
    python -m src.cli audit --viewer org-gx
    python -m src.cli stale --viewer org-a
    python -m src.cli html --viewer org-gx --out workbench.html
"""

import argparse
from pathlib import Path

from src.domain import load_workbench
from src.page import render_workbench_html
from src.workbench import (
    STAGE_NAMES,
    all_impacts,
    decision_audit,
    open_actions,
    stale_filings,
    visible_applications,
    workbench_view,
)

DEFAULT_DATA = Path("fixtures/domain.json")
DEFAULT_AS_OF = "2026-09-27"


def _load(args) -> dict:
    return load_workbench(Path(args.data))


def _cmd_workbench(args) -> None:
    data = _load(args)
    view = workbench_view(data, args.viewer, args.as_of)
    print(f"查看者：{view['viewer']['name']}　数据日期：{view['as_of']}")
    for stage in view["stages"]:
        print(f"\n【{stage['name']}】{stage['description']}")
        if not stage["applications"]:
            print("  （暂无申请）")
        for card in stage["applications"]:
            print(f"  ● {card['product_name']} · {card['country']} · 代理：{card['agent']}")
            print(f"    路径：{card['path']['classification']}；{card['path']['route']}")
            for action in card["next_actions"][:3]:
                owner = f"（{action['owner']}，期限 {action['due_on']}）" if action["owner"] else ""
                print(f"    → {action['text']}{owner}")


def _cmd_actions(args) -> None:
    data = _load(args)
    rows = open_actions(data, args.viewer, args.as_of)
    if not rows:
        print("当前没有未办结的补件或驳回。")
        return
    for a in rows:
        state = f"逾期 {-a['days_left']} 天" if a["overdue"] else f"剩余 {a['days_left']} 天"
        print(f"[{a['kind_name']}] {a['application_name']}：{a['title']}")
        print(f"    责任人：{a['owner_org_name']}·{a['owner']['person']}　期限 {a['due_on']}（{state}）")


def _cmd_impacts(args) -> None:
    data = _load(args)
    for impact in all_impacts(data, args.viewer, args.as_of):
        event = impact["event"]
        print(f"[{impact['type_name']}] {event['summary']}（{event['occurred_on']}）")
        for hit in impact["affected"]:
            print(f"    波及 {hit['application_name']}：")
            for reason in hit["reasons"]:
                print(f"      - {reason}")
        for note in impact["notes"]:
            print(f"    提示：{note}")


def _cmd_audit(args) -> None:
    data = _load(args)
    names = {
        "ok": "与当前版本一致",
        "superseded": "判断后证据已更新",
        "stale_at_decision": "判断时已有更新版本",
        "expired": "判断时版本已过期",
    }
    for row in decision_audit(data, args.viewer, args.as_of):
        print(f"[{row['kind']}] {row['application_name']}（{row['decided_on']}，{row['decided_by']}）")
        print(f"    结论：{row['outcome']}")
        for e in row["evidence"]:
            print(f"    证据：{e['artifact_title']} 钉住 {e['pinned']}（当前 {e['current']}）→ {names[e['status']]}")


def _cmd_stale(args) -> None:
    data = _load(args)
    rows = stale_filings(data, args.viewer, args.as_of)
    if not rows:
        print("未发现旧版资料申报风险。")
        return
    for s in rows:
        print(f"[{s['application_name']}] {s['note']}")


def _cmd_html(args) -> None:
    data = _load(args)
    view = workbench_view(data, args.viewer, args.as_of)
    out = Path(args.out)
    out.write_text(render_workbench_html(view), encoding="utf-8")
    print(f"已生成 {out}（查看者：{view['viewer']['name']}）")


def main(argv=None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--data", default=str(DEFAULT_DATA), help="领域资料路径")
    common.add_argument("--viewer", default="org-gx", help="查看者机构 id")
    common.add_argument("--as-of", default=DEFAULT_AS_OF, help="数据日期（YYYY-MM-DD）")
    parser = argparse.ArgumentParser(description="创新药械东盟准入统一工作台")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("workbench", parents=[common], help="四阶段工作台总览")
    commands.add_parser("actions", parents=[common], help="补件/驳回待办（责任人、期限）")
    commands.add_parser("impacts", parents=[common], help="变更事件影响分析")
    commands.add_parser("audit", parents=[common], help="准入判断证据版本稽核")
    commands.add_parser("stale", parents=[common], help="旧版资料申报风险")
    html_cmd = commands.add_parser("html", parents=[common], help="导出自包含 HTML 工作台")
    html_cmd.add_argument("--out", default="workbench.html", help="输出文件")
    args = parser.parse_args(argv)
    {
        "workbench": _cmd_workbench,
        "actions": _cmd_actions,
        "impacts": _cmd_impacts,
        "audit": _cmd_audit,
        "stale": _cmd_stale,
        "html": _cmd_html,
    }[args.command](args)


if __name__ == "__main__":
    main()
