"""Public-news truthfulness, source identity, freshness and zero-key integration."""
from datetime import datetime, timedelta, timezone
import socket
from types import SimpleNamespace
from unittest.mock import Mock

from src.services.intelligence_service import FeedEntry, IntelligenceService
from src.services.personal_investment_report import PersonalInvestmentReport
from src.services.public_news_service import PublicNewsService, canonical_url, relevant_news

NOW = datetime(2026, 10, 18, 8, tzinfo=timezone.utc)


def entry(title='Circle Internet Group reports USDC update', url='https://finance.yahoo.com/news/circle',
          stamp=NOW - timedelta(hours=2), **metadata):
    return FeedEntry(title, 'SYNTHETIC source summary', url, 'SYNTHETIC feed', stamp, metadata)


def test_feed_metadata_dedup_dates_and_identity_are_not_invented():
    reader = SimpleNamespace(_fetch_feed_entries=Mock(return_value=[
        entry(), entry(url='https://finance.yahoo.com/news/circle?utm_source=duplicate'),
        entry(title='CRCL token launch on an unrelated chain', url='https://finance.yahoo.com/news/token'),
        entry(stamp=NOW - timedelta(days=4)), entry(stamp=None), entry(stamp=NOW + timedelta(hours=1)),
        entry(url='https://unrated.invalid/circle'), entry(url='http://finance.yahoo.com/news/circle')]))
    service = PublicNewsService(None, NOW, reader=reader)
    rows, quality = service.collect('CRCL', 'Circle Internet Group')
    assert len(rows) == 1 and rows[0]['source'] == 'finance.yahoo.com'
    assert rows[0]['published_at'] == (NOW - timedelta(hours=2)).isoformat()
    assert '未核验全文' in rows[0]['evidence_scope']
    assert quality['rejected'] == {'missing_date': 1, 'stale_or_future': 2, 'unrelated': 1,
                                   'source_or_url': 2, 'duplicate': 1}
    assert service.collect('CRCL', 'Circle Internet Group') == (rows, quality)
    assert reader._fetch_feed_entries.call_count == 1


def test_second_public_source_is_transparent_aggregation_and_preserves_original_date():
    reader = SimpleNamespace(_fetch_feed_entries=Mock(side_effect=[[], [
        entry(title='Robinhood Markets event update', url='https://news.google.com/rss/articles/SYNTHETIC',
              publisher='Reuters', publisher_url='https://www.reuters.com')]]))
    rows, quality = PublicNewsService(None, NOW, reader=reader).collect('HOOD', 'Robinhood Markets')
    assert len(rows) == 1 and rows[0]['link_kind'] == '聚合入口'
    assert rows[0]['source'] == 'www.reuters.com'
    assert len(quality['attempts']) == 2


def test_failure_and_no_coverage_are_cached_without_creating_news():
    reader = SimpleNamespace(_fetch_feed_entries=Mock(side_effect=[TimeoutError('SYNTHETIC'), []]))
    service = PublicNewsService(None, NOW, reader=reader)
    rows, quality = service.collect('CRCL', 'Circle Internet Group')
    assert rows == [] and quality['status'] == 'unavailable'
    assert service.collect('CRCL', 'Circle Internet Group') == (rows, quality)
    assert reader._fetch_feed_entries.call_count == 2


def test_ticker_names_cannot_substitute_for_company_or_crypto_identity():
    assert not relevant_news('CRCL', 'Circle Internet Group', 'CRCL meme token and chain launch')
    assert relevant_news('CRCL', 'Circle Internet Group', 'Circle expands USDC payments')
    assert not relevant_news('HOOD', 'Robinhood Markets', 'Robin Hood movie costume')
    assert not relevant_news('ETH', 'Ethereum', 'ETH Zurich research paper')
    assert relevant_news('BTC', 'Bitcoin', 'Bitcoin ETF inflows')
    assert canonical_url('https://SYNTHETIC_USER:SYNTHETIC_PASSWORD@finance.yahoo.com/news') == ''
    assert canonical_url('https://finance.yahoo.com/news?a=1&utm_campaign=x#tracking') == 'https://finance.yahoo.com/news?a=1'


def test_existing_rss_parser_preserves_publisher_provenance(monkeypatch):
    monkeypatch.setattr('src.services.intelligence_service.socket.getaddrinfo',
                        lambda *args: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 0))])
    reader = object.__new__(IntelligenceService)  # Parsing does not need a database or configuration.
    xml = b'<rss><channel><item><title>SYNTHETIC Circle update</title><link>https://news.google.com/rss/articles/SYNTHETIC</link><source url="https://www.reuters.com">Reuters</source><pubDate>Sun, 18 Oct 2026 07:00:00 GMT</pubDate></item></channel></rss>'
    parsed = reader._parse_feed(xml, source_name='SYNTHETIC Google feed', limit=5)
    assert parsed[0].raw_payload['publisher_url'] == 'https://www.reuters.com'
    assert parsed[0].raw_payload['publisher'] == 'Reuters'


def test_personal_report_falls_back_without_search_keys(monkeypatch):
    config = SimpleNamespace(tavily_api_keys=[], serpapi_keys=[], brave_api_keys=[], social_sentiment_api_key=None)
    report = object.__new__(PersonalInvestmentReport)
    report.config, report.now = config, NOW
    report.session = {'session': '2026-10-16', 'close_utc': '2026-10-16T20:00:00+00:00'}
    report.stock = SimpleNamespace(get_daily_data=Mock(side_effect=RuntimeError('SYNTHETIC no prices')))
    report._public_news = None
    ticker = SimpleNamespace(get_info=lambda: {'quoteType': 'EQUITY', 'currency': 'USD',
                                             'longName': 'Circle Internet Group'}, news=[])
    collector = SimpleNamespace(collect=Mock(return_value=([{'title': 'SYNTHETIC sourced headline'}], {'status': 'available'})))
    monkeypatch.setattr('src.services.personal_investment_report.yf.Ticker', lambda _: ticker)
    monkeypatch.setattr('src.services.public_news_service.PublicNewsService', lambda *args: collector)
    monkeypatch.setenv('PUBLIC_NEWS_FALLBACK_ENABLED', 'true')
    result = report.evidence('CRCL')
    assert result['news'][0]['title'] == 'SYNTHETIC sourced headline'
    assert result['quote'] is None  # News never becomes a fabricated price or technical signal.
    assert result['news_monitor']['status'] == 'available'
    collector.collect.assert_called_once_with('CRCL', 'Circle Internet Group')
