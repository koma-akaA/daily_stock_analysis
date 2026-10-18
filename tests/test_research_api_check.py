"""Real failure contracts: no credentials in output, no neutral fallback or duplicate calls."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

from scripts.check_research_apis import has_budget, redact, run_checks, usage_snapshot
from src.services.social_sentiment_service import SocialSentimentService


def response(status=200, data=None, headers=None):
    return SimpleNamespace(status_code=status, headers=headers or {}, json=lambda: data or {})


def test_direct_stock_endpoints_find_nontrending_ticker_and_cache():
    service = SocialSentimentService('SYNTHETIC_ADANOS', 'https://api.example.invalid')
    payload = {'ticker': 'CRCL', 'found': True, 'mentions': 8, 'sentiment_score': 0}
    with patch('src.services.social_sentiment_service._get_with_retry', return_value=response(data=payload)) as get:
        context = service.get_social_context('CRCL', include_polymarket=False)
        assert 'Reddit：提及8，情绪0' in context
        assert 'X：提及8，情绪0' in context
        assert [call.args[0].split('.invalid')[1] for call in get.call_args_list] == [
            '/reddit/stocks/v1/stock/CRCL', '/x/stocks/v1/stock/CRCL']
        assert service.get_social_context('CRCL', include_polymarket=False) == context
        assert get.call_count == 2


def test_found_false_does_not_become_neutral_and_is_cached():
    service = SocialSentimentService('SYNTHETIC_ADANOS')
    with patch('src.services.social_sentiment_service._get_with_retry',
               return_value=response(data={'ticker': 'HOOD', 'found': False, 'mentions': 0, 'sentiment_score': 0})) as get:
        assert service.fetch_x_report('HOOD') is None
        assert service.fetch_x_report('HOOD') is None
        assert get.call_count == 1


@pytest.mark.parametrize('status', [401, 429])
def test_invalid_key_or_exhausted_quota_stops_further_requests(status):
    service = SocialSentimentService('SYNTHETIC_ADANOS')
    with patch('src.services.social_sentiment_service._get_with_retry', return_value=response(status=status)) as get:
        assert service.fetch_reddit_report('CRCL') is None
        assert service.fetch_x_report('HOOD') is None
        assert get.call_count == 1


def test_failure_logs_do_not_include_exception_credentials(caplog):
    key = 'SYNTHETIC_ADANOS_PRIVATE'
    service = SocialSentimentService(key)
    with patch('src.services.social_sentiment_service._get_with_retry', side_effect=requests.Timeout(key)) as get:
        assert service.fetch_reddit_report('CRCL') is None
        assert service.fetch_reddit_report('CRCL') is None
        assert get.call_count == 1
    assert key not in caplog.text


@pytest.mark.parametrize('url', ['http://api.example.invalid', 'https://name:secret@api.example.invalid',
                                 'https://api.example.invalid/docs', 'https://api.example.invalid?token=secret'])
def test_no_credentials_sent_to_insecure_or_malformed_base_url(url):
    with pytest.raises(ValueError):
        SocialSentimentService('SYNTHETIC_ADANOS', url)


def test_usage_is_whitelisted_and_exhausted_plan_does_not_use_paygo():
    payload = {'key': {'usage': 3, 'limit': None, 'api_key': 'SYNTHETIC_PRIVATE'},
               'account': {'plan_usage': 1000, 'plan_limit': 1000, 'paygo_limit': 100, 'email': 'private'}}
    with patch('scripts.check_research_apis.requests.get', return_value=response(data=payload)):
        snapshot = usage_snapshot('SYNTHETIC_PRIVATE')
    assert 'SYNTHETIC_PRIVATE' not in str(snapshot)
    assert 'private' not in str(snapshot)
    assert not has_budget(snapshot)


def test_missing_keys_are_not_reported_as_tested():
    config = SimpleNamespace(social_sentiment_api_key=None, social_sentiment_api_url='https://api.adanos.org',
                             tavily_api_keys=[])
    with patch('scripts.check_research_apis.requests.get') as get:
        report, code = run_checks(config)
    assert code == 1
    assert report['adanos']['status'] == report['tavily']['status'] == 'not_tested'
    get.assert_not_called()
    assert redact({'value': 'SYNTHETIC_PRIVATE'}, ['SYNTHETIC_PRIVATE']) == {'value': '[REDACTED]'}
