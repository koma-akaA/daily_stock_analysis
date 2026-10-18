#!/usr/bin/env python3
"""Daily research / test notification. No trading functionality."""
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_config  # noqa: E402
from src.notification_sender.pushplus_sender import PushplusSender  # noqa: E402
from src.services.investment_history import InvestmentHistory  # noqa: E402
from src.services.personal_investment_report import (  # noqa: E402
    DEFAULT_ASSETS, PersonalInvestmentReport, render_report,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("analysis", "push-test"), default="analysis")
    parser.add_argument("--no-ai", action="store_true")
    parser.add_argument("--no-notify", action="store_true")
    parser.add_argument("--no-history", action="store_true")
    parser.add_argument("--scheduled", action="store_true")
    parser.add_argument("--resend", action="store_true", help="Explicitly allow another push for this Beijing date")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    now = datetime.now(timezone.utc)
    beijing = now.astimezone(ZoneInfo("Asia/Shanghai"))
    if args.scheduled and (beijing.weekday() not in range(1, 6) or not 8 <= beijing.hour < 14):
        print("Scheduled run outside Beijing Tue-Sat morning window; skipped")
        return 0
    config = get_config()
    folder = Path("reports/personal")
    folder.mkdir(parents=True, exist_ok=True)
    date = beijing.date().isoformat()
    run_id = os.getenv("GITHUB_RUN_ID", now.strftime("%H%M%S"))
    key = date if args.mode == "analysis" and not args.resend else f"{date}-{args.mode}-{run_id}"
    history = None if args.no_history else InvestmentHistory(os.getenv("GITHUB_REPOSITORY", ""), os.getenv("GITHUB_TOKEN", ""))
    state_path = f"state/{key}.json"
    if history and not args.no_notify and history.read(state_path):
        print("Durable notification claim already exists; skipped to avoid duplicate delivery")
        return 0
    history_path = f"reports/{date}/{run_id}.md"
    history_url = history.url(history_path) if history else ""
    if args.mode == "push-test":
        body = (f"# 【微信推送测试】\n\n北京时间：{beijing.isoformat(timespec='seconds')}\n\n"
                "个人微信 · PushPlus公众号渠道\n\n换行、中文与英文 CRCL / BTC / ETH 显示测试。\n\n"
                "这是一条接收测试，不包含投资结论。请在微信打开全文核对排版。\n")
        report = {"mode": "push-test", "generated_at": now.isoformat()}
        complete = True
    else:
        symbols = list(dict.fromkeys(s.strip().upper() for s in os.getenv("INVESTMENT_ASSETS", DEFAULT_ASSETS).split(",") if s.strip()))
        if not symbols or len(symbols) > 15 or any(not re.fullmatch(r"[A-Z]{1,5}(?:\.[A-Z])?", s) for s in symbols):
            raise ValueError("Use up to 15 US tickers or BTC/ETH in INVESTMENT_ASSETS")
        if "CRCL" in symbols:
            symbols.remove("CRCL")
            symbols.insert(0, "CRCL")
        report = PersonalInvestmentReport(config, now).build(symbols, ai=not args.no_ai)
        body = render_report(report, history_url=history_url)
        complete = all(a["quote"] and a["technicals"] and (args.no_ai or a["ai"]["status"] == "generated") for a in report["assets"])
    full = render_report(report, full=True) if args.mode == "analysis" else body
    (folder / "report.md").write_text(full, encoding="utf-8")
    (folder / "wechat.md").write_text(body, encoding="utf-8")
    (folder / "evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    import markdown2
    for name, content in (("report", full), ("wechat", body)):
        markup = markdown2.markdown(content, safe_mode="escape")
        page = ('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>每日投资分析</title><style>body{max-width:390px;margin:20px auto;padding:16px;font:16px/1.7 system-ui;'
                'overflow-wrap:anywhere;background:#fafafa;color:#182230}h1{font-size:24px}h2{font-size:21px;border-top:1px solid #ddd;'
                'padding-top:20px}a{color:#1264a3}p{margin:12px 0}</style>' + markup + '</html>')
        (folder / f"{name}.html").write_text(page, encoding="utf-8")
    files = {history_path: full, history_path.replace(".md", ".json"): json.dumps(report, ensure_ascii=False, allow_nan=False),
             "README.md": "# 投资研究历史\n\n[本次完整报告](" + history_path + ")\n\n历史按日期保存在 reports/。数据与推断分别展示；不执行交易。\n"}
    if args.no_notify:
        if history:
            history.save(files, f"Archive investment research {date}")
        print("Report generated; notification deliberately disabled")
        return 0 if complete else 1
    if not config.pushplus_token:
        print("PUSHPLUS_TOKEN missing: no message sent", file=sys.stderr)
        if history:
            history.save(files, f"Archive research without configured notification {date}")
        return 1
    if len(body.encode("utf-8")) > 18000:
        # Avoid many messages / rate limits. Full report always survives in history/artifacts.
        body = body.encode("utf-8")[:16500].decode("utf-8", errors="ignore") + "\n\n摘要已截短；完整报告：" + history_url
    state = {"status": "claimed", "date_beijing": date, "run_id": run_id,
             "body_sha256": hashlib.sha256(body.encode()).hexdigest(), "report": history_path}
    if history:
        files[state_path] = json.dumps(state, ensure_ascii=False)
        history.save(files, f"Claim investment notification {key}")  # Failure here prevents POST.
    sender = PushplusSender(config)
    accepted = sender.send_to_pushplus(body, title=f"每日投资分析 {date}" if args.mode == "analysis" else "微信推送测试", timeout_seconds=20)
    state["status"] = sender.last_delivery_status
    state["response_code"] = sender.last_response_code
    # Short codes grant access to report content. Keep them out of a possibly public history branch.
    (folder / "notification.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    if history:
        history.save({state_path: json.dumps(state, ensure_ascii=False)}, f"Record notification result {key}")
    print(f"PushPlus status={state['status']}; accepted={accepted}; final WeChat delivery requires receiver confirmation")
    return 0 if accepted and complete else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # API/SDK exceptions must never dump tokens, request bodies or authorization headers.
        print(f"Investment run failed: {type(error).__name__}; inspect configuration/network and report quality", file=sys.stderr)
        raise SystemExit(1)
