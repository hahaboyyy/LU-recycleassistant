import json

import pytest

from reco.client import ChatClient, EmptyResponseError, OutputLimitError, NetworkError
from reco.config import Config


@pytest.mark.parametrize('content', ['', '{"item_id":"office_paper"}'])
def test_length_limited_output_is_never_accepted_or_retried_at_same_budget(content):
    calls = []
    def transport(payload):
        calls.append(payload)
        return 200, {}, json.dumps({'choices': [{'message': {'content': content}, 'finish_reason': 'length'}]})
    client = ChatClient(Config(max_retries=2), transport=transport)
    with pytest.raises(OutputLimitError):
        client.chat([])
    assert len(calls) == 1
    assert calls[0]['max_tokens'] == 4096


def test_empty_stop_response_remains_distinct_from_output_limit():
    transport = lambda payload: (200, {}, json.dumps({'choices': [{'message': {'content': ''}, 'finish_reason': 'stop'}]}))
    with pytest.raises(EmptyResponseError):
        ChatClient(Config(max_retries=0), transport=transport).chat([])


def test_one_transient_retry_can_recover_without_changing_budget(monkeypatch):
    calls = []
    def transport(payload):
        calls.append(payload)
        if len(calls) == 1:
            raise NetworkError('temporary read failure')
        return 200, {}, json.dumps({'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}]})
    client = ChatClient(Config(max_retries=1), transport=transport)
    monkeypatch.setattr(client, '_sleep', lambda seconds: None)
    result = client.chat([])
    assert result.attempts == 2
    assert [call['max_tokens'] for call in calls] == [4096, 4096]

