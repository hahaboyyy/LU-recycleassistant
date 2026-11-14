import json
from reco.client import LLMResponse
from reco.config import Config
from reco.pipeline import Recognizer


class Responses:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.messages = []
    def chat(self, messages):
        self.messages.append(messages)
        return LLMResponse(text=json.dumps(next(self.outputs)),model='test',latency_ms=2,
                           prompt_tokens=10,completion_tokens=5,finish_reason='stop')


def test_uncertain_paper_gets_one_visual_check_without_reference_answers(tmp_path, photo):
    client = Responses([
        {'identification':{'name_en':'Printed sheet'},'item_id':'unknown','item_id_candidates':['office_paper','magazine_paper']},
        {'identification':{'name_en':'Office paper'},'item_id':'office_paper'},
    ])
    rec = Recognizer(Config(provider='deepseek',log_path=str(tmp_path/'log.jsonl')),client=client)
    result = rec.recognize(photo)
    assert result.item_id == 'office_paper'
    assert len(client.messages) == 2
    assert result.trace.attempts == 2
    assert result.trace.prompt_tokens == 20
    assert 'hypotheses, not correct labels' in client.messages[1][0]['content']


def test_material_ambiguity_remains_a_user_question(tmp_path, photo):
    client = Responses([{'identification':{'name_en':'Bottle'},'item_id':'unknown',
                         'item_id_candidates':['plastic_beverage_bottle','glass_beverage_bottle']}])
    rec = Recognizer(Config(provider='deepseek',log_path=str(tmp_path/'log.jsonl')),client=client)
    result = rec.recognize(photo)
    assert result.catalogue_status == 'ambiguous'
    assert len(client.messages) == 1
