import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.services.investment_history import InvestmentHistory


def test_conflicting_claim_is_not_force_pushed():
    obj = InvestmentHistory('SYNTHETIC/repo', 'SYNTHETIC_TOKEN')
    calls = []

    def request(method, path, payload=None, missing=False):
        calls.append((method, path, payload))
        if '/git/ref/heads/' in path:
            return {'object': {'sha': 'old'}}
        if path == '/git/commits/old':
            return {'tree': {'sha': 'tree'}}
        if path == '/git/trees':
            return {'sha': 'new-tree'}
        if path == '/git/commits':
            return {'sha': 'new'}
        if method == 'PATCH':
            assert payload['force'] is False
            raise RuntimeError('GitHub history HTTP 422')
        raise AssertionError(path)

    obj.request = request
    with pytest.raises(RuntimeError):
        obj.save({'state/day.json': 'claimed'}, 'claim')
    assert calls[-1][0] == 'PATCH'


def load_cli():
    path = Path(__file__).resolve().parents[1] / 'scripts/personal_investment.py'
    spec = importlib.util.spec_from_file_location('personal_cli', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_claim_failure_prevents_any_push(monkeypatch, tmp_path):
    module = load_cli()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr('sys.argv', ['script', '--mode', 'push-test'])
    monkeypatch.setattr(module, 'get_config', lambda: SimpleNamespace(pushplus_token='SYNTHETIC_TOKEN'))
    history = SimpleNamespace(read=lambda _: None, url=lambda _: 'https://github.com/SYNTHETIC/repo',
                              save=Mock(side_effect=RuntimeError('Cannot persist claim')))
    monkeypatch.setattr(module, 'InvestmentHistory', lambda *a: history)
    send = Mock()
    monkeypatch.setattr(module, 'PushplusSender', send)
    with pytest.raises(RuntimeError):
        module.main()
    send.assert_not_called()


def test_existing_claim_skips_data_ai_and_notification(monkeypatch):
    module = load_cli()
    monkeypatch.setattr('sys.argv', ['script'])
    monkeypatch.setattr(module, 'get_config', lambda: SimpleNamespace())
    monkeypatch.setattr(module, 'InvestmentHistory', lambda *a: SimpleNamespace(read=lambda _: '{"status":"unknown"}'))
    build = Mock()
    send = Mock()
    monkeypatch.setattr(module, 'PersonalInvestmentReport', build)
    monkeypatch.setattr(module, 'PushplusSender', send)
    assert module.main() == 0
    build.assert_not_called()
    send.assert_not_called()
