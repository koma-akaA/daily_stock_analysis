"""Synthetic fixtures exercise truthfulness, session timing and asset identity."""
from datetime import datetime, timezone, date
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from data_provider.crypto_fetcher import CryptoFetcher
from src.services.personal_investment_report import (
    AI_FIELDS, TECHNICAL_PROSE, PersonalInvestmentReport, technical_facts, technical_readout,
    us_session_context, validate_bars, yahoo_news,
)


def bars(count=90, crypto=True):
    dates = pd.date_range('2026-01-01', periods=count, freq='D')
    return pd.DataFrame({'date': dates, 'open': range(100, 100 + count),
                         'high': range(102, 102 + count), 'low': range(99, 99 + count),
                         'close': range(101, 101 + count), 'volume': [1000] * count})


@pytest.mark.parametrize('stamp,session,close', [
    ('2026-07-08T00:30:00+00:00', '2026-07-07', '20:00'),  # DST
    ('2026-12-09T00:30:00+00:00', '2026-12-08', '21:00'),  # standard time
    ('2026-12-26T00:30:00+00:00', '2026-12-24', '18:00'),  # holiday + early close
    ('2026-10-18T00:30:00+00:00', '2026-10-16', '20:00'),  # weekend
])
def test_last_completed_us_session(stamp, session, close):
    result = us_session_context(datetime.fromisoformat(stamp))
    assert result['session'] == session
    assert close in result['close_utc']


def test_no_open_session_used():
    result = us_session_context(datetime.fromisoformat('2026-10-16T19:59:00+00:00'))
    assert result['session'] == '2026-10-15'


def test_stale_missing_and_nonfinite_bars_rejected():
    df = bars()
    expected = df.iloc[-1].date.date()
    assert len(validate_bars(df, expected, crypto=True)) == 90
    with pytest.raises(ValueError):
        validate_bars(df.iloc[:-1], expected, crypto=True)
    with pytest.raises(ValueError):
        validate_bars(df.drop(42), expected, crypto=True)
    df.loc[10, 'close'] = float('nan')
    with pytest.raises(ValueError):
        validate_bars(df, expected, crypto=True)


def test_ma60_never_uses_ma20_fallback():
    assert technical_facts(bars(59), 'BTC') is None
    facts = technical_facts(bars(90), 'BTC')
    assert facts['ma60'] == pytest.approx(bars(90).close.tail(60).mean())
    assert facts['ma60'] != facts['ma20']
    assert '右侧' in facts['trend']
    assert '未出现新金叉' in facts['double_ma']


def test_range_support_and_resistance_remain_available_below_moving_averages():
    df = bars(90)
    # Synthetic completed candle breaks below all MAs but remains above its low.
    df.loc[89, ['open', 'high', 'low', 'close']] = [180, 182, 147, 150]
    facts = technical_facts(df, 'CRCL')
    assert facts['support'] == 147
    assert 150 < facts['resistance'] < df.high.tail(20).max()
    assert 0 < facts['stop_reference'] < facts['support']
    # Crypto levels are filtered around the current spot snapshot, not a stale daily close.
    spot = technical_facts(df, 'BTC', reference_price=145)
    assert spot['support'] is None
    assert spot['resistance'] == 147


def test_crypto_identity_is_explicit():
    with pytest.raises(KeyError):
        CryptoFetcher().daily('CRCL')


def test_crypto_excludes_incomplete_day():
    now = datetime(2026, 1, 4, 1, tzinfo=timezone.utc)
    rows = [[int(datetime(2026, 1, day, tzinfo=timezone.utc).timestamp()), 99, 102, 100, 101, 10]
            for day in (2, 3, 4)]
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: rows)
    session = SimpleNamespace(headers={}, mount=lambda *a: None, get=lambda *a, **k: response)
    df = CryptoFetcher(session).daily('BTC', now)
    assert df.iloc[-1].date.date() == date(2026, 1, 3)
    assert len(df) == 2


def test_news_requires_date_and_safe_url():
    ticker = SimpleNamespace(news=[{'content': {'title': 'SYNTHETIC news',
             'pubDate': '2026-10-16T12:00:00Z', 'canonicalUrl': {'url': 'https://news.invalid/a'}}},
             {'content': {'title': 'No date', 'canonicalUrl': {'url': 'https://news.invalid/b'}}}])
    assert len(yahoo_news(ticker, datetime(2026, 10, 18, tzinfo=timezone.utc))) == 1


def test_ai_never_called_without_quote():
    report = object.__new__(PersonalInvestmentReport)
    assert report.interpret({'quote': None})['status'] == 'unavailable'


def test_valuation_support_phrase_does_not_bypass_technical_fact_guard():
    # Live CRCL prose was rejected even after repair because this financial phrase
    # contains 支撑. Allow only the specific nontechnical phrase, never support levels.
    assert not TECHNICAL_PROSE.search('缺少经营数据，无法判断估值是否被基本面支撑')
    for text in ('支撑位尚待确认', '基本面支撑位在八十美元', '基本面支撑区',
                 '基本面支撑价格', '基本面支撑但长期均线高于中期均线'):
        assert TECHNICAL_PROSE.search(text)
    facts = {'symbol': 'CRCL', 'asset_class': 'US equity', 'quote': {'price': 80},
             'technicals': {'ma20': 90, 'ma60': 70, 'levels_reference_price': 80},
             'fundamentals': {'market_cap': 100}, 'news': [], 'social': None}
    claims = {key: {'text': '等待确认并限制单次风险预算', 'evidence': ['technical:price_ma20']}
              for key in AI_FIELDS}
    claims['valuation'] = {'text': '无法判断估值是否被基本面支撑，快照仅作参照', 'evidence': ['fundamentals']}
    calls = []

    def generate(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(text=json.dumps(claims), model='SYNTHETIC', provider='SYNTHETIC')

    report = object.__new__(PersonalInvestmentReport)
    report._analyzer = SimpleNamespace(generate_text_with_metadata=generate)
    assert report.interpret(facts)['status'] == 'generated'
    assert len(calls) == 1  # No paid wording retry for a valid financial phrase.


def test_ai_rejects_unknown_evidence_reference():
    report = object.__new__(PersonalInvestmentReport)
    report._analyzer = SimpleNamespace(generate_text_with_metadata=lambda *a, **k:
                                      SimpleNamespace(text='{"valuation":{"text":"invented","evidence":["fake"]}}',
                                                      model='SYNTHETIC', provider='SYNTHETIC'))
    facts = {'quote': {'price': 100}, 'technicals': None, 'fundamentals': None, 'news': [], 'social': None}
    assert report.interpret(facts)['status'] == 'unavailable'


def test_crypto_prompt_does_not_assign_crcl_research_focus():
    report = object.__new__(PersonalInvestmentReport)
    captured = []

    def generate(prompt, **kwargs):
        captured.append(prompt)
        return None

    report._analyzer = SimpleNamespace(generate_text_with_metadata=generate)
    report.interpret({'symbol': 'BTC', 'name': 'Bitcoin', 'asset_class': 'crypto',
                      'quote': {'price': 100}, 'technicals': {}, 'fundamentals': None,
                      'news': [], 'social': None, 'ai': {'text': 'SYNTHETIC_OLD_ANALYSIS'}})
    assert '唯一分析对象是BTC' in captured[0]
    assert '本轮CRCL优先研究' not in captured[0]
    assert 'SYNTHETIC_OLD_ANALYSIS' not in captured[0]


def test_technical_relationships_are_computed_not_rewritten_by_ai():
    facts = {'symbol': 'SYNTHETIC', 'asset_class': 'US equity', 'quote': {'price': 80},
             'technicals': {'ma20': 90, 'ma60': 70, 'double_ma': 'MA20高于MA60',
                            'levels_reference_price': 80},
             'fundamentals': None, 'news': [], 'social': None}
    readout = technical_readout(facts)
    assert readout['price_ma20'] == '最近收盘价低于MA20'
    assert readout['price_ma60'] == '最近收盘价高于MA60'
    assert readout['double_ma'] == 'MA20高于MA60'
    report = object.__new__(PersonalInvestmentReport)
    claims = {key: {'text': '等待更多证据确认，限制单次风险预算',
                    'evidence': ['technical:price_ma20']} for key in AI_FIELDS}

    def generate(*args, **kwargs):
        return SimpleNamespace(text=json.dumps(claims), model='SYNTHETIC', provider='SYNTHETIC')

    report._analyzer = SimpleNamespace(generate_text_with_metadata=generate)
    assert report.interpret(facts)['status'] == 'generated'
    # This actually happened in live QA: vague period names inverted a true relationship.
    claims['long_term']['text'] = '长期均线仍高于中期均线'
    assert report.interpret(facts)['status'] == 'unavailable'
    claims['long_term']['text'] = '中期均线上方形成支撑'
    assert report.interpret(facts)['status'] == 'unavailable'
    calls = []

    def repair_once(prompt, **kwargs):
        calls.append(prompt)
        text = json.dumps(claims) if len(calls) == 1 else json.dumps({'long_term': '长期条件尚待验证'})
        return SimpleNamespace(text=text, model='SYNTHETIC', provider='SYNTHETIC')

    report._analyzer = SimpleNamespace(generate_text_with_metadata=repair_once)
    repaired = report.interpret(facts)
    assert len(calls) == 2
    assert repaired['status'] == 'generated'
    assert repaired['repaired_fields'] == ['long_term']
    assert repaired['long_term']['text'] == '长期条件尚待验证'
    assert repaired['long_term']['evidence'] == ['technical:price_ma20']
