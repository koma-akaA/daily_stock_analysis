#!/usr/bin/env python3
"""Bounded CRCL/HOOD API checks. No AI, notifications, key values or raw responses."""
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import get_config  # noqa: E402
from src.search_service import SearchService, TavilySearchProvider  # noqa: E402
from src.services.social_sentiment_service import SocialSentimentService  # noqa: E402

TARGETS = {"CRCL": "Circle Internet Group", "HOOD": "Robinhood Markets"}


def safe_number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def redact(value, secrets):
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {key: redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    return value


def usage_snapshot(key):
    """GET /usage with a fixed host; only numeric budget fields leave this function."""
    try:
        response = requests.get("https://api.tavily.com/usage", headers={"Authorization": "Bearer " + key},
                                timeout=20, allow_redirects=False)
        result = {"http_status": response.status_code}
        if response.status_code == 200:
            data = response.json()
            for section, fields in {"key": ("usage", "limit", "search_usage"),
                                    "account": ("plan_usage", "plan_limit", "paygo_usage", "paygo_limit")}.items():
                result[section] = {field: safe_number((data.get(section) or {}).get(field)) for field in fields}
        return result
    except Exception as exc:
        return {"http_status": None, "error_type": type(exc).__name__}


def has_budget(snapshot):
    """Do not search against a known exhausted quota or consume extra pay-as-you-go."""
    for section, used, limit in (("key", "usage", "limit"), ("account", "plan_usage", "plan_limit")):
        values = snapshot.get(section) or {}
        ceiling, consumed = values.get(limit), values.get(used)
        if ceiling is not None and consumed is not None and ceiling >= 0 and consumed >= ceiling:
            return False
    return True


def check_social(service):
    checks = []
    for symbol in TARGETS:
        for platform, fetch in (("reddit", service.fetch_reddit_report), ("x", service.fetch_x_report)):
            data = fetch(symbol)
            path = f"/{platform}/stocks/v1/stock/{symbol}"
            info = dict(service.request_info.get(path, {}))
            row = {"symbol": symbol, "platform": platform, **info}
            report = data.get("report", data) if data else {}
            row["coverage"] = "available" if report else "unavailable"
            row["mentions"] = safe_number(report.get("mentions", report.get("total_mentions")))
            row["sentiment_score"] = safe_number(report.get("sentiment_score"))
            before = service.request_count
            cached = fetch(symbol)
            row["repeat_used_cache"] = cached == data and before == service.request_count
            checks.append(row)
    return checks


def run_checks(config):
    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat(), "targets": list(TARGETS),
              "configured": {"social_key": bool(config.social_sentiment_api_key),
                             "social_url": bool(config.social_sentiment_api_url),
                             "tavily_keys": bool(config.tavily_api_keys)}}
    errors = []
    if config.social_sentiment_api_key:
        try:
            social = SocialSentimentService(config.social_sentiment_api_key, config.social_sentiment_api_url)
            result["adanos"] = check_social(social)
            if any(row.get("http_status") != 200 or not row["repeat_used_cache"] for row in result["adanos"]):
                errors.append("Adanos checks incomplete or failed; inspect per-endpoint statuses")
        except Exception as exc:
            result["adanos"] = {"status": "failed", "error_type": type(exc).__name__}
            errors.append("Adanos configuration or response failure")
    else:
        result["adanos"] = {"status": "not_tested", "reason": "API key missing"}
        errors.append("Adanos API key missing")

    if not config.tavily_api_keys:
        result["tavily"] = {"status": "not_tested", "reason": "TAVILY_API_KEYS missing"}
    else:
        # Test the first configured key only. No key cycling or redundant search variants.
        key = config.tavily_api_keys[0]
        before = usage_snapshot(key)
        news = {"usage_before": before, "checks": []}
        if before.get("http_status") in (401, 429) or not has_budget(before):
            news["status"] = "skipped_auth_or_quota"
            errors.append("Tavily authentication or quota preflight failed")
        else:
            search = SearchService(tavily_keys=[key], searxng_public_instances_enabled=False)
            provider = next(p for p in search._providers if isinstance(p, TavilySearchProvider))
            remaining = min((values[limit] - values[used]
                             for section, used, limit in (("key", "usage", "limit"), ("account", "plan_usage", "plan_limit"))
                             if (values := before.get(section, {})).get(limit) is not None
                             and values.get(used) is not None and values[limit] >= 0), default=2)
            for symbol, name in TARGETS.items():
                if remaining < 1:
                    news["checks"].append({"symbol": symbol, "status": "skipped_quota"})
                    errors.append("Tavily remaining budget insufficient for another search")
                    break
                response = search.search_stock_news(symbol, name, max_results=3)
                calls_before = provider.request_count
                # Failed requests are not repeated just to test cache behavior.
                repeated = search.search_stock_news(symbol, name, max_results=3) if response.success else None
                row = {"symbol": symbol, "success": response.success, "http_status": provider.last_http_status,
                       "usable_news_count": len(response.results), "usage": provider.last_usage,
                       "repeat_used_cache": calls_before == provider.request_count and repeated == response,
                       "articles": [{"title": item.title, "url": item.url, "published_date": item.published_date}
                                    for item in response.results]}
                news["checks"].append(row)
                remaining -= provider.last_usage.get("credits", 1)
                if not row["success"] or not row["repeat_used_cache"]:
                    errors.append("Tavily search failed or repeated its request")
            news["usage_after"] = usage_snapshot(key)
            news["status"] = "tested"
            if any(news[name].get("http_status") != 200 for name in ("usage_before", "usage_after")):
                errors.append("Tavily usage could not be verified")
        result["tavily"] = news
    result["errors"] = errors
    result["status"] = "failed" if errors else "passed" if config.tavily_api_keys else "partial_tavily_not_configured"
    return redact(result, [config.social_sentiment_api_key, *config.tavily_api_keys]), 1 if errors else 0


def main():
    logging.disable(logging.CRITICAL)  # Third-party SDK messages are not part of the safe report.
    result, code = run_checks(get_config())
    folder = Path("reports/api-check")
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return code


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"API check failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1)
