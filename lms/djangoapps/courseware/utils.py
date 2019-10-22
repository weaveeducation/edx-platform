from collections import OrderedDict
from django.utils.html import strip_tags
from submissions import api as sub_data_api


CREDO_GRADED_ITEM_CATEGORIES = ['problem', 'drag-and-drop-v2', 'openassessment']


def _get_item_correctness(item):
    id_list = item.lcp.correct_map.keys()
    answer_notification_type = None

    if len(id_list) == 1:
        # Only one answer available
        answer_notification_type = item.lcp.correct_map.get_correctness(id_list[0])
    elif len(id_list) > 1:
        # Check the multiple answers that are available
        answer_notification_type = item.lcp.correct_map.get_correctness(id_list[0])
        for answer_id in id_list[1:]:
            if item.lcp.correct_map.get_correctness(answer_id) != answer_notification_type:
                # There is at least 1 of the following combinations of correctness states
                # Correct and incorrect, Correct and partially correct, or Incorrect and partially correct
                # which all should have a message type of Partially Correct
                if item.lcp.disable_partial_credit:
                    answer_notification_type = 'incorrect'
                else:
                    answer_notification_type = 'partially correct'
                break
    return answer_notification_type


def get_block_children(block, parent_name, add_correctness=True):
    data = OrderedDict()
    for item in block.get_children():
        loc_id = str(item.location)
        data[loc_id] = get_problem_detailed_info(item, parent_name, add_correctness)
        if item.has_children:
            data.update(get_block_children(item, item.display_name, add_correctness))
    return data


def get_problem_detailed_info(item, parent_name, add_correctness=True):
    brs_tags = ['<br>', '<br/>', '<br />']
    res = {'data': item, 'category': item.category, 'parent_name': parent_name, 'id': str(item.location)}
    if item.category in CREDO_GRADED_ITEM_CATEGORIES:
        res['correctness'] = ''
        res['question_text'] = ''
        res['question_text_safe'] = ''
        res['category'] = item.category

        if item.category == 'problem':
            if add_correctness:
                correctness = _get_item_correctness(item)
                res['correctness'] = correctness if correctness else None
            question_text = ''
            dt = item.index_dictionary(remove_variants=True)
            if dt and 'content' in dt and 'capa_content' in dt['content']:
                question_text = dt['content']['capa_content'].strip()
            res['question_text'] = question_text
            res['question_text_safe'] = question_text

        elif item.category == 'openassessment':
            prompts = []
            for pr in item.prompts:
                pr_descr = pr['description']
                for br_val in brs_tags:
                    pr_descr = pr_descr.replace(br_val, "\n")
                prompts.append(strip_tags(pr_descr).strip())

            if len(prompts) > 1:
                res['question_text'] = "<br />".join([p.replace('\n', '<br />') for p in prompts])
                res['question_text_safe'] = "\n".join(prompts)
            elif len(prompts) == 1:
                res['question_text'] = prompts[0].replace('\n', '<br />')
                res['question_text_safe'] = prompts[0]

        elif item.category == 'drag-and-drop-v2':
            res['question_text'] = item.question_text
            res['question_text_safe'] = item.question_text
    return res


def _get_dnd_answer_values(item_state, zones):
    result = {}
    items = {}
    some_value = False
    for it in zones['items']:
        items[str(it['id'])] = it['displayName']
    idx = 0
    for z in zones['zones']:
        res = []
        result[str(idx)] = '--'
        for k, v in item_state.items():
            if z['uid'] == v['zone']:
                res.append(items[str(k)])
        if res:
            result[str(idx)] = ', '.join(sorted(res))
            some_value = True
        idx = idx + 1
    return result if some_value else {}


def get_answer_and_correctness(user_state_dict, score, category, block, key,
                               submission=None, submission_uuid=None):
    answer = {}
    correctness = None

    if category == 'problem' and user_state_dict:
        answer_state = user_state_dict.get(str(key))
        if answer_state:
            state_gen = block.generate_report_data([answer_state])
            for state_username, state_item in state_gen:
                tmp_answer = state_item.get('Answer')
                answer[state_item.get('Answer ID')] = tmp_answer.strip().replace('\n', ' ') \
                    if tmp_answer is not None else ''
    elif category == 'openassessment':
        submission_dict = None
        if submission:
            submission_dict = submission.copy()
        if submission_uuid:
            submission_dict = sub_data_api.get_submission(submission_uuid)
        if submission_dict:
            if 'answer' in submission_dict and 'parts' in submission_dict['answer']:
                for answ_idx, answ_val in enumerate(submission_dict['answer']['parts']):
                    answer[str(answ_idx)] = answ_val['text']
    elif category == 'drag-and-drop-v2':
        answer_state = user_state_dict.get(str(key))
        if answer_state:
            answer = _get_dnd_answer_values(answer_state.state['item_state'], block.data)
        else:
            answer = _get_dnd_answer_values(block.item_state, block.data)

    if answer:
        if score.earned == 0:
            correctness = 'incorrect'
        elif score.possible == score.earned:
            correctness = 'correct'
        else:
            correctness = 'partially correct'

    return answer, correctness


def get_score_points(score_points):
    return int(score_points) if int(score_points) == score_points else score_points
