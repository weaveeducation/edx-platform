"""Utility functions that have to do with the courseware."""


import datetime
import hashlib
import logging

from collections import OrderedDict
from django.utils.html import strip_tags
from submissions import api as sub_data_api

from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from edx_rest_api_client.client import OAuthAPIClient
from oauth2_provider.models import Application
from pytz import utc  # lint-amnesty, pylint: disable=wrong-import-order
from rest_framework import status
from xmodule.partitions.partitions import \
    ENROLLMENT_TRACK_PARTITION_ID  # lint-amnesty, pylint: disable=wrong-import-order
from xmodule.partitions.partitions_service import PartitionService  # lint-amnesty, pylint: disable=wrong-import-order

from common.djangoapps.course_modes.models import CourseMode
from lms.djangoapps.commerce.utils import EcommerceService
from lms.djangoapps.courseware.config import ENABLE_NEW_FINANCIAL_ASSISTANCE_FLOW
from lms.djangoapps.courseware.constants import (
    UNEXPECTED_ERROR_APPLICATION_STATUS,
    UNEXPECTED_ERROR_CREATE_APPLICATION,
    UNEXPECTED_ERROR_IS_ELIGIBLE
)
from lms.djangoapps.courseware.models import FinancialAssistanceConfiguration
from openedx.core.djangoapps.waffle_utils.models import WaffleFlagCourseOverrideModel

log = logging.getLogger(__name__)


CREDO_GRADED_ITEM_CATEGORIES = [
    'problem',
    'drag-and-drop-v2',
    'openassessment',
    'image-explorer',
    'freetextresponse',
    'text-highlighter',
]


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


def is_mode_upsellable(user, enrollment, course=None):
    """
    Return whether the user is enrolled in a mode that can be upselled to another mode,
    usually audit upselled to verified.
    The partition code allows this function to more accurately return results for masquerading users.

    Arguments:
        user (:class:`.AuthUser`): The user from the request.user property
        enrollment (:class:`.CourseEnrollment`): The enrollment under consideration.
        course (:class:`.ModulestoreCourse`): Optional passed in modulestore course.
            If provided, it is expected to correspond to `enrollment.course.id`.
            If not provided, the course will be loaded from the modulestore.
            We use the course to retrieve user partitions when calculating whether
            the upgrade link will be shown.
    """
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
    upsellable_mode = not current_mode or current_mode in CourseMode.UPSELL_TO_VERIFIED_MODES
    return upsellable_mode


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

    if not is_mode_upsellable(user, enrollment, course):
        return False

    upgrade_deadline = enrollment.upgrade_deadline

    if upgrade_deadline is None:
        return False

    if datetime.datetime.now(utc).date() > upgrade_deadline.date():
        return False

    # Show the summary if user enrollment is in which allow user to upsell
    return enrollment.is_active and enrollment.mode in CourseMode.UPSELL_TO_VERIFIED_MODES


def _request_financial_assistance(method, url, params=None, data=None):
    """
    An internal function containing common functionality among financial assistance utility function to call
    edx-financial-assistance backend with appropriate method, url, params and data.
    """
    financial_assistance_configuration = FinancialAssistanceConfiguration.current()
    if financial_assistance_configuration.enabled:
        oauth_application = Application.objects.get(
            user=financial_assistance_configuration.get_service_user(),
            authorization_grant_type=Application.GRANT_CLIENT_CREDENTIALS
        )
        client = OAuthAPIClient(
            settings.LMS_ROOT_URL,
            oauth_application.client_id,
            oauth_application.client_secret
        )
        return client.request(
            method, f"{financial_assistance_configuration.api_base_url}{url}", params=params, data=data
        )
    else:
        return False, 'Financial Assistance configuration is not enabled'


def is_eligible_for_financial_aid(course_id):
    """
    Sends a get request to edx-financial-assistance to retrieve financial assistance eligibility criteria for a course.

    Returns either True if course is eligible for financial aid or vice versa.
    Also returns the reason why the course isn't eligible.
    In case of a bad request, returns an error message.
    """
    response = _request_financial_assistance('GET', f"{settings.IS_ELIGIBLE_FOR_FINANCIAL_ASSISTANCE_URL}{course_id}/")
    if response.status_code == status.HTTP_200_OK:
        return response.json().get('is_eligible'), response.json().get('reason')
    elif response.status_code == status.HTTP_400_BAD_REQUEST:
        return False, response.json().get('message')
    else:
        log.error('%s %s', UNEXPECTED_ERROR_IS_ELIGIBLE, str(response.content))
        return False, UNEXPECTED_ERROR_IS_ELIGIBLE


def get_financial_assistance_application_status(user_id, course_id):
    """
    Given the course_id, sends a get request to edx-financial-assistance to retrieve
    financial assistance application(s) status for the logged-in user.
    """
    request_params = {
        'course_id': course_id,
        'lms_user_id': user_id
    }
    response = _request_financial_assistance(
        'GET', f"{settings.FINANCIAL_ASSISTANCE_APPLICATION_STATUS_URL}", params=request_params
    )
    if response.status_code == status.HTTP_200_OK:
        return True, response.json()
    elif response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND):
        return False, response.json().get('message')
    else:
        log.error('%s %s', UNEXPECTED_ERROR_APPLICATION_STATUS, response.content)
        return False, UNEXPECTED_ERROR_APPLICATION_STATUS


def create_financial_assistance_application(form_data):
    """
    Sends a post request to edx-financial-assistance to create a new application for financial assistance application.
    The incoming form_data must have data as given in the example below:
    {
        "lms_user_id": <user_id>,
        "course_id": <course_run_id>,
        "income": <income_from_range>,
        "learner_reasons": <TEST_LONG_STRING>,
        "learner_goals": <TEST_LONG_STRING>,
        "learner_plans": <TEST_LONG_STRING>,
        "allow_for_marketing": <Boolean>
    }
    """
    response = _request_financial_assistance(
        'POST', f"{settings.CREATE_FINANCIAL_ASSISTANCE_APPLICATION_URL}/", data=form_data
    )
    if response.status_code == status.HTTP_200_OK:
        return HttpResponse(status=status.HTTP_204_NO_CONTENT)
    elif response.status_code == status.HTTP_400_BAD_REQUEST:
        log.error(response.json().get('message'))
        return HttpResponseBadRequest(response.content)
    else:
        log.error('%s %s', UNEXPECTED_ERROR_CREATE_APPLICATION, response.content)
        return HttpResponse(status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def get_course_hash_value(course_key):
    """
    Returns a hash value for the given course key.
    If course key is None, function returns an out of bound value which will
    never satisfy the fa_backend_enabled_courses_percentage condition
    """
    out_of_bound_value = 100
    if course_key:
        m = hashlib.md5(str(course_key).encode())
        return int(m.hexdigest(), base=16) % 100

    return out_of_bound_value


def _use_new_financial_assistance_flow(course_id):
    """
    Returns if the course_id can be used in the new financial assistance flow.
    """
    is_financial_assistance_enabled_for_course = WaffleFlagCourseOverrideModel.override_value(
        ENABLE_NEW_FINANCIAL_ASSISTANCE_FLOW.name, course_id
    )
    financial_assistance_configuration = FinancialAssistanceConfiguration.current()
    if financial_assistance_configuration.enabled and (
            is_financial_assistance_enabled_for_course == WaffleFlagCourseOverrideModel.ALL_CHOICES.on or
            get_course_hash_value(course_id) <= financial_assistance_configuration.fa_backend_enabled_courses_percentage
    ):
        return True
    return False


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
            question_text = strip_tags(item.question_text)
            res['question_text'] = question_text
            res['question_text_safe'] = question_text
            res['question_text_list'] = [question_text]

        elif item.category == 'image-explorer':
            description = strip_tags(item.student_view_data()['description'])
            res['question_text'] = description
            res['question_text_safe'] = description
            res['question_text_list'] = [description]

        elif item.category == 'text-highlighter':
            descr1 = item.description
            descr2 = item.text
            for br_val in brs_tags:
                descr1 = descr1.replace(br_val, "\n")
                descr2 = descr2.replace(br_val, "\n")
            description_lst = [d for d in [strip_tags(descr1), strip_tags(descr2)] if d]
            res['question_text'] = "<br />".join(description_lst)
            res['question_text_safe'] = "\n".join(description_lst)
            res['question_text_list'] = description_lst[:]

        elif item.category == 'freetextresponse':
            description = strip_tags(item.prompt)
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
    elif category == 'text-highlighter':
        answer_state = user_state_dict.get(str(key))
        if answer_state:
            user_answers = answer_state.state.get('user_answers', [])
            if user_answers:
                answer['student_answer'] = '; '.join(user_answers)
    elif category == 'freetextresponse':
        answer_state = user_state_dict.get(str(key))
        if answer_state:
            answer['student_answer'] = answer_state.state.get('student_answer')

    if answer:
        correctness = get_correctness(score) if score else None

    return answer, correctness


def get_score_points(score_points):
    return int(score_points) if int(score_points) == score_points else score_points


def get_correctness(score):
    if score.possible == score.earned:
        return 'correct'
    elif score.earned == 0:
        return 'incorrect'
    else:
        return 'partially correct'


def get_lti_context_session_key(usage_id):
    return 'lti_context_id_' + str(usage_id)
