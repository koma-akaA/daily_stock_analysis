"""Keyless public-news monitoring. Reuses the upstream bounded RSS/DNS-safe reader."""
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from src.services.intelligence_service import IntelligenceService


ISSUER_DOMAINS = ('circle.com', 'robinhood.com', 'aboutrobinhood.com', 'coinbase.com', 'tesla.com')
MEDIA_DOMAINS = ('finance.yahoo.com', 'reuters.com', 'bloomberg.com', 'cnbc.com', 'wsj.com', 'ft.com',
                 'apnews.com', 'marketwatch.com', 'barrons.com', 'coindesk.com', 'theblock.co',
                 'decrypt.co', 'unchainedcrypto.com', 'cointelegraph.com', 'globenewswire.com',
                 'businesswire.com', 'prnewswire.com', 'benzinga.com', 'fool.com', 'seekingalpha.com')
IDENTITY_PATTERNS = {
    'CRCL': r'circle internet|circle.{0,80}(?:usdc|crcl|stablecoin|stock|shares)|\bcrcl\b.{0,50}(?:stock|shares|nyse)',
    'HOOD': r'\brobinhood\b', 'COIN': r'\bcoinbase\b', 'TSLA': r'\btesla\b',
    'BTC': r'\bbitcoin\b', 'ETH': r'\bethereum\b|\bether\b.{0,35}(?:crypto|token|market)',
}


def canonical_url(value):
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return ''
    pairs = [(key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
             if not key.lower().startswith('utm_') and key.lower() not in {'.tsrc', 'gclid', 'fbclid'}]
    return urlunsplit((parsed.scheme, parsed.netloc.lower(), parsed.path, urlencode(pairs), ''))


def matches_domain(host, domains):
    return any(host == domain or host.endswith('.' + domain) for domain in domains)


def relevant_news(symbol, name, text):
    return bool(re.search(IDENTITY_PATTERNS.get(symbol, re.escape(name)), text, re.I))


class PublicNewsService:
    """At most two public feed requests per asset; cache even missing coverage for this run."""

    def __init__(self, config, now=None, reader=None):
        self.now = now or datetime.now(timezone.utc)
        self.reader = reader or IntelligenceService(config=config)
        self._cache = {}

    def collect(self, symbol, name, limit=5):
        if symbol in self._cache:
            return self._cache[symbol]
        ticker = {'BTC': 'BTC-USD', 'ETH': 'ETH-USD'}.get(symbol, symbol)
        # These are public syndication feeds, not authenticated search APIs.
        feeds = [('Yahoo Finance RSS', 'https://finance.yahoo.com/rss/headline?' + urlencode({'s': ticker})),
                 ('Google News RSS', 'https://news.google.com/rss/search?' + urlencode({
                     'q': f'"{name}" when:3d', 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'}))]
        items, attempts, seen_urls, seen_titles = [], [], set(), set()
        rejected = {'missing_date': 0, 'stale_or_future': 0, 'unrelated': 0, 'source_or_url': 0, 'duplicate': 0}
        for source, feed_url in feeds:
            try:
                # Reuse the project's size limit, bounded redirects, DNS checks, XML/date parser.
                entries = self.reader._fetch_feed_entries({'name': source, 'url': feed_url, 'source_type': 'rss'}, limit=40)
                attempts.append({'source': source, 'status': 'fetched', 'received': len(entries)})
            except Exception as exc:
                attempts.append({'source': source, 'status': 'unavailable', 'error_type': type(exc).__name__})
                continue
            for entry in entries:
                if entry.published_at is None:
                    rejected['missing_date'] += 1
                    continue
                stamp = entry.published_at.replace(tzinfo=timezone.utc) if entry.published_at.tzinfo is None else entry.published_at
                if not timedelta(minutes=-5) <= self.now - stamp <= timedelta(days=3):
                    rejected['stale_or_future'] += 1
                    continue
                text = entry.title + ' ' + entry.summary
                if not relevant_news(symbol, name, text):
                    rejected['unrelated'] += 1
                    continue
                url = canonical_url(entry.url)
                host = (urlsplit(url).hostname or '').lower()
                aggregate = host == 'news.google.com'
                publisher_url = str(entry.raw_payload.get('publisher_url', '')) if aggregate else url
                publisher_host = (urlsplit(publisher_url).hostname or '').lower()
                official = matches_domain(publisher_host, ISSUER_DOMAINS)
                if not url or not (official or matches_domain(publisher_host, MEDIA_DOMAINS)):
                    rejected['source_or_url'] += 1
                    continue
                normalized_title = re.sub(r'\W+', '', entry.title.casefold())
                if url in seen_urls or normalized_title in seen_titles:
                    rejected['duplicate'] += 1
                    continue
                seen_urls.add(url)
                seen_titles.add(normalized_title)
                items.append({'title': entry.title, 'summary': entry.summary[:500], 'url': url,
                              'published_at': stamp.astimezone(timezone.utc).isoformat(),
                              'source': publisher_host, 'collected_at': self.now.isoformat(),
                              'collector': source, 'link_kind': '聚合入口' if aggregate else '原文入口',
                              'verification': '公司消息线索' if official else '媒体报道线索',
                              'evidence_scope': '仅核验RSS标题、摘要与发布时间，未核验全文或事件真实性'})
            if items:
                break  # Do not query another feed when usable coverage already exists.
        items.sort(key=lambda row: row['published_at'], reverse=True)
        result = (items[:limit], {'status': 'available' if items else 'unavailable',
                                 'checked_at': self.now.isoformat(), 'attempts': attempts, 'rejected': rejected})
        self._cache[symbol] = result
        return result
