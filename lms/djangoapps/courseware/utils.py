"""Utility functions that have to do with the courseware."""


import datetime

from django.conf import settings
from lms.djangoapps.commerce.utils import EcommerceService
from pytz import utc  # lint-amnesty, pylint: disable=wrong-import-order

from common.djangoapps.course_modes.models import CourseMode
from xmodule.partitions.partitions import ENROLLMENT_TRACK_PARTITION_ID
from xmodule.partitions.partitions_service import PartitionService
from collections import OrderedDict
from django.utils.html import strip_tags
from submissions import api as sub_data_api


CREDO_GRADED_ITEM_CATEGORIES = ['problem', 'drag-and-drop-v2', 'openassessment', 'image-explorer']


def verified_upgrade_deadline_link(user, course=None, course_id=None):
    """
    Format the correct verified upgrade link for the specified ``user``
    in a course.

    One of ``course`` or ``course_id`` must be supplied. If both are specified,
    ``course`` will take priority.

    Arguments:
        user (:class:`~django.contrib.auth.models.User`): The user to display
            the link for.
        course (:class:`.CourseOverview`): The course to render a link for.
        course_id (:class:`.CourseKey`): The course_id of the course to render for.

    Returns:
        The formatted link that will allow the user to upgrade to verified
        in this course.
    """
    if course is not None:
        course_id = course.id
    return EcommerceService().upgrade_url(user, course_id)


def can_show_verified_upgrade(user, enrollment, course=None):
    """
    Return whether this user can be shown upgrade message.

    Arguments:
        user (:class:`.AuthUser`): The user from the request.user property
        enrollment (:class:`.CourseEnrollment`): The enrollment under consideration.
            If None, then the enrollment is not considered to be upgradeable.
        course (:class:`.ModulestoreCourse`): Optional passed in modulestore course.
            If provided, it is expected to correspond to `enrollment.course.id`.
            If not provided, the course will be loaded from the modulestore.
            We use the course to retrieve user partitions when calculating whether
            the upgrade link will be shown.
    """
    if enrollment is None:
        return False  # this got accidentally flipped in 2017 (commit 8468357), but leaving alone to not switch again
    partition_service = PartitionService(enrollment.course.id, course=course)
    enrollment_track_partition = partition_service.get_user_partition(ENROLLMENT_TRACK_PARTITION_ID)
    group = partition_service.get_group(user, enrollment_track_partition)
    current_mode = None
    if group:
        try:
            current_mode = [
                mode.get('slug') for mode in settings.COURSE_ENROLLMENT_MODES.values() if mode['id'] == group.id
            ].pop()
        except IndexError:
            pass
    upgradable_mode = not current_mode or current_mode in CourseMode.UPSELL_TO_VERIFIED_MODES

    if not upgradable_mode:
        return False

    upgrade_deadline = enrollment.upgrade_deadline

    if upgrade_deadline is None:
        return False

    if datetime.datetime.now(utc).date() > upgrade_deadline.date():
        return False

    # Show the summary if user enrollment is in which allow user to upsell
    return enrollment.is_active and enrollment.mode in CourseMode.UPSELL_TO_VERIFIED_MODES


def _get_item_correctness(item):
    id_list = list(item.lcp.correct_map.keys())
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
    if block.category == 'library_content' and block.xmodule_runtime is not None:
        children = block.get_child_descriptors()
    else:
        children = block.get_children()
    for item in children:
        loc_id = str(item.location)
        data[loc_id] = get_problem_detailed_info(item, parent_name, add_correctness)
        if item.has_children:
            data.update(get_block_children(item, item.display_name, add_correctness))
    return data


def get_problem_detailed_info(item, parent_name, add_correctness=True):
    brs_tags = ['<br>', '<br/>', '<br />']
    res = {
        'data': item,
        'category': item.category,
        'has_children': item.has_children,
        'parent_name': parent_name,
        'id': str(item.location)
    }
    if item.category in CREDO_GRADED_ITEM_CATEGORIES:
        res['correctness'] = ''
        res['question_text'] = ''
        res['question_text_safe'] = ''
        res['category'] = item.category
        res['hidden'] = False

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
            res['question_text_list'] = dt['content']['capa_content_lst']
            res['possible_options'] = dt['content']['possible_options']

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
                res['question_text_list'] = prompts[:]
            elif len(prompts) == 1:
                res['question_text'] = prompts[0].replace('\n', '<br />')
                res['question_text_safe'] = prompts[0]
                res['question_text_list'] = prompts[:]
            res['hidden'] = item.is_hidden()

        elif item.category == 'drag-and-drop-v2':
            res['question_text'] = item.question_text
            res['question_text_safe'] = item.question_text
            res['question_text_list'] = [item.question_text]

        elif item.category == 'image-explorer':
            description = item.student_view_data()['description']
            res['question_text'] = description
            res['question_text_safe'] = description
            res['question_text_list'] = [description]
    return res


def _get_dnd_answer_values(item_state, zones):
    if not item_state:
        return {}
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
            if z['uid'] == v['zone'] and str(k) in items:
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
            try:
                state_gen = block.generate_report_data([answer_state])
                for state_username, state_item in state_gen:
                    tmp_answer = state_item.get('Answer')
                    answer[state_item.get('Answer ID')] = tmp_answer.strip().replace('\n', ' ') \
                        if tmp_answer is not None else ''
            except AssertionError:
                correctness = get_correctness(score) if score else None
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
            answer = _get_dnd_answer_values(answer_state.state.get('item_state', {}), block.data)
        else:
            answer = _get_dnd_answer_values(block.item_state, block.data)
    elif category == 'image-explorer':
        answer_state = user_state_dict.get(str(key))
        if answer_state:
            opened_hotspots_cnt = len(answer_state.state.get('opened_hotspots', []))
            answer['opened_hotspots'] = 'Opened hotspots: ' + str(opened_hotspots_cnt)

    if answer:
        correctness = get_correctness(score) if score else None

    return answer, correctness


def get_score_points(score_points):
    return int(score_points) if int(score_points) == score_points else score_points


def get_correctness(score):
    if score.earned == 0:
        return 'incorrect'
    elif score.possible == score.earned:
        return 'correct'
    else:
        return 'partially correct'


def get_lti_context_session_key(usage_id):
    return 'lti_context_id_' + str(usage_id)
