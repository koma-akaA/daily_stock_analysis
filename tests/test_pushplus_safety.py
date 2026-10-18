from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

from src.notification_sender.pushplus_sender import PushplusSender


def sender():
    return PushplusSender(SimpleNamespace(pushplus_token='SYNTHETIC_TOKEN', pushplus_max_bytes=20000))


@patch('src.notification_sender.pushplus_sender.requests.post')
def test_https_personal_wechat_and_accepted_is_not_delivery(post):
    post.return_value = SimpleNamespace(status_code=200, json=lambda: {'code': 200, 'data': 'SYNTHETIC_SHORT'})
    obj = sender()
    assert obj.send_to_pushplus('中文\n\n排版测试')
    assert post.call_args.args[0] == 'https://www.pushplus.plus/send'
    assert post.call_args.kwargs['json']['channel'] == 'wechat'
    assert obj.last_delivery_status == 'accepted'
    assert obj.last_short_codes == ['SYNTHETIC_SHORT']


@patch('src.notification_sender.pushplus_sender.requests.post')
def test_timeout_does_not_resend_or_expose_credentials(post, caplog):
    post.side_effect = requests.Timeout('SYNTHETIC_TOKEN in response')
    obj = sender()
    assert not obj.send_to_pushplus('content')
    assert post.call_count == 1
    assert obj.last_delivery_status == 'unknown'
    assert 'SYNTHETIC_TOKEN' not in caplog.text


@patch('src.notification_sender.pushplus_sender.requests.post')
def test_business_failure_stops_all_remaining_chunks(post):
    post.return_value = SimpleNamespace(status_code=200, json=lambda: {'code': 900, 'msg': 'SYNTHETIC_TOKEN'})
    obj = sender()
    assert not obj.send_to_pushplus('中' * 20000)
    assert post.call_count == 1
    assert obj.last_delivery_status == 'rejected'
    assert obj.last_response_code == 900
