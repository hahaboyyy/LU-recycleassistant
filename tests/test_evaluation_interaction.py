from evaluation.evaluate_systems import interactive


def test_key_based_fixture_reuses_existing_answer_in_alternative_question_order():
    first = {'status': 'ok', 'action': 'clarify_item', 'question': 'Food jar or bottle?', 'question_key': 'package_type'}
    case = {'question_key_1': 'material', 'user_answer_1': 'Glass',
            'question_key_2': 'package_type', 'user_answer_2': 'A glass food jar'}
    histories = []
    def predict(**kwargs):
        histories.append(kwargs['history'])
        return {'action': 'give_advice', 'item_id': 'glass_food_jar', 'advice': 'Rinse the jar.'}
    calls, history, stop = interactive(predict, first, 'unused.jpg', case, fixture_policy='by_key')
    assert stop == ''
    assert history[0]['answer'] == 'A glass food jar'
    assert calls[-1]['item_id'] == 'glass_food_jar'


def test_key_based_fixture_does_not_invent_missing_answers():
    first = {'status': 'ok', 'action': 'clarify_item', 'question': 'What material?', 'question_key': 'material'}
    case = {'question_key_1': '', 'user_answer_1': '', 'question_key_2': '', 'user_answer_2': ''}
    def predict(**kwargs):
        raise AssertionError('No answer is available, so prediction must not be called')
    calls, history, stop = interactive(predict, first, 'unused.jpg', case, fixture_policy='by_key')
    assert stop == 'question_without_fixture'
    assert not history
