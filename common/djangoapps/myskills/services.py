import json
import time
from datetime import timedelta
from collections import OrderedDict
from django.http import Http404
from django.utils.html import escape
from lms.djangoapps.courseware.courses import get_course_with_access
from lms.djangoapps.courseware.module_render import get_module_by_usage_id
from lms.djangoapps.courseware.utils import CREDO_GRADED_ITEM_CATEGORIES, get_block_children, get_score_points,\
    get_answer_and_correctness
from lms.djangoapps.courseware.user_state_client import DjangoXBlockUserStateClient
from lms.djangoapps.grades.api import CourseGradeFactory
from common.djangoapps.credo_modules.models import CredoModulesUserProfile
from openedx.core.djangoapps.user_api.accounts.utils import is_user_credo_anonymous
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey, UsageKey
from .extended_progress import tags_student_progress, assessments_progress
from .utils import convert_into_tree


class MySkillsService:
    student = None
    course = None
    courseware_summary = None

    def __init__(self, student, course):
        self.student = student
        self.course = course

    def _get_course_problem_blocks(self):
        return modulestore().get_items(self.course.id, qualifiers={'category': {'$in': CREDO_GRADED_ITEM_CATEGORIES}})

    def _get_courseware_summary(self):
        if not self.courseware_summary:
            course_grade = CourseGradeFactory().read(self.student, self.course)
            self.courseware_summary = course_grade.chapter_grades.values()
        return self.courseware_summary

    def get_tags_summary(self):
        problem_blocks = self._get_course_problem_blocks()
        courseware_summary = self._get_courseware_summary()

        tags = tags_student_progress(self.course, self.student, problem_blocks, courseware_summary)
        tags_to_100 = sorted(tags, key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
        tags_from_100 = sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))

        context = {
            'top5tags': tags_from_100[:5],
            'lowest5tags': tags_to_100[:5],
        }
        return context

    def get_tags_all_data(self):
        problem_blocks = self._get_course_problem_blocks()
        courseware_summary = self._get_courseware_summary()

        tags = tags_student_progress(self.course, self.student, problem_blocks, courseware_summary, group_tags=True)
        tags_assessments = [v.copy() for v in tags if v['tag_is_last']]

        tags = convert_into_tree(tags)
        tags_assessments = sorted(tags_assessments, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))

        context = {
            'tags': tags,
            'tags_assessments': tags_assessments,
            'url_api_get_tag_data': '',
            'url_api_get_tag_section_data': '',
            'api_student_id': 0,
            'api_org': ''
        }
        return context

    def get_assessment_summary(self, include_data_str=True):
        courseware_summary = self._get_courseware_summary()
        assessments = assessments_progress(courseware_summary, include_data_str=include_data_str)
        return assessments

    def get_assessment_all_data(self, include_data_str=True):
        problems_dict = {}
        problem_blocks = self._get_course_problem_blocks()
        for pr in problem_blocks:
            parent = pr.get_parent()
            if parent is None:
                continue
            problems_dict[str(pr.location)] = {
                'display_name': pr.display_name,
                'vertical_id': None,
                'vertical_name': '',
                'hidden': False
            }
            if pr.category == 'openassessment':
                problems_dict[str(pr.location)]['hidden'] = pr.is_hidden()
            if parent.category == 'vertical':
                problems_dict[str(pr.location)]['vertical_id'] = str(parent.location)
                problems_dict[str(pr.location)]['vertical_name'] = parent.display_name
            else:
                parent = parent.get_parent()
                if parent.category == 'vertical':
                    problems_dict[str(pr.location)]['vertical_id'] = str(parent.location)
                    problems_dict[str(pr.location)]['vertical_name'] = parent.display_name
                else:
                    raise Exception("Can't find vertical block for element: " + str(pr.location))

        courseware_summary = self._get_courseware_summary()
        assessments = assessments_progress(courseware_summary, problems_dict, include_data_str=include_data_str)

        context = {
            'assessments': assessments
        }
        return context


def _get_browser_datetime(last_answer_datetime, timezone_offset=None, dt_format=None):
    if dt_format is None:
        dt_format = '%Y-%m-%d %H:%M'
    if timezone_offset is not None:
        if timezone_offset > 0:
            last_answer_datetime = last_answer_datetime + timedelta(minutes=timezone_offset)
        else:
            timezone_offset = (-1) * timezone_offset
            last_answer_datetime = last_answer_datetime - timedelta(minutes=timezone_offset)
    return last_answer_datetime.strftime(dt_format)


def get_block_student_progress(request, course_id, usage_id, timezone_offset=None):
    course_key = CourseKey.from_string(course_id)
    full_name = str(request.user.first_name) + ' ' + str(request.user.last_name)

    resp = {
        'error': False,
        'common': {},
        'items': [],
        'user': {
            'username': request.user.username,
            'email': request.user.email,
            'full_name': full_name.strip()
        }
    }

    question_categories = (
        'openassessment',
        'drag-and-drop-v2',
        'image-explorer',
        'freetextresponse',
        'text_highlighter'
    )

    try:
        with modulestore().bulk_operations(course_key):
            usage_key = UsageKey.from_string(usage_id)

            course = get_course_with_access(request.user, 'load', course_key)

            credo_anonymous_name_is_set = False
            credo_anonymous_email_is_set = False
            is_credo_anonymous = is_user_credo_anonymous(request.user)

            if is_credo_anonymous and course.credo_additional_profile_fields:
                profile = CredoModulesUserProfile.objects.filter(course_id=course_key, user=request.user).first()
                if profile:
                    profile_fileds = json.loads(profile.meta)
                    if 'name' in profile_fileds:
                        resp['user']['username'] = profile_fileds['name']
                        credo_anonymous_name_is_set = True
                    if 'email' in profile_fileds:
                        resp['user']['email'] = profile_fileds['email']
                        credo_anonymous_email_is_set = True

            if not resp['user']['full_name']:
                resp['user']['full_name'] = resp['user']['username']
                if is_credo_anonymous and not credo_anonymous_name_is_set:
                    resp['user']['full_name'] = None

            if is_credo_anonymous and not credo_anonymous_email_is_set:
                resp['user']['email'] = None

            seq_item, _ = get_module_by_usage_id(
                request, str(course_key), str(usage_key), disable_staff_debug_info=True, course=course
            )
            children_dict = get_block_children(seq_item, seq_item.display_name)
            user_state_client = DjangoXBlockUserStateClient(request.user)
            user_state_dict = {}
            problem_locations = [item['data'].location for k, item in children_dict.items()
                                 if item['category'] in (
                                     'problem', 'image-explorer', 'freetextresponse', 'text_highlighter'
                                 )]

            if problem_locations:
                user_state_dict = user_state_client.get_all_blocks(request.user, course_key, problem_locations)

            course_grade = CourseGradeFactory().read(request.user, course)
            courseware_summary = course_grade.chapter_grades.values()

            for chapter in courseware_summary:
                for section in chapter['sections']:
                    if str(section.location) == str(usage_id):
                        resp['common']['quiz_name'] = seq_item.display_name
                        resp['common']['last_answer_timestamp'] = section.last_answer_timestamp
                        resp['common']['unix_timestamp'] = int(time.mktime(section.last_answer_timestamp.timetuple())) \
                            if section.last_answer_timestamp else None
                        resp['common']['browser_datetime'] = _get_browser_datetime(section.last_answer_timestamp,
                                                                                   timezone_offset) \
                            if section.last_answer_timestamp else ''
                        resp['common']['browser_datetime_short'] = _get_browser_datetime(section.last_answer_timestamp,
                                                                                         timezone_offset,
                                                                                         "%B %d, %Y") \
                            if section.last_answer_timestamp else ''
                        resp['common']['percent_graded'] = int(section.percent_graded * 100)
                        resp['common'].update(section.percent_info)
                        if int(resp['common']['earned']) == resp['common']['earned']:
                            resp['common']['earned'] = int(resp['common']['earned'])
                        if int(resp['common']['possible']) == resp['common']['possible']:
                            resp['common']['possible'] = int(resp['common']['possible'])

                        for key, score in section.problem_scores.items():
                            item = children_dict.get(str(key))
                            if item and not item.get('hidden', False) and item['category'] in CREDO_GRADED_ITEM_CATEGORIES:
                                submission_uuid = None
                                if item['category'] == 'openassessment':
                                    submission_uuid = item['data'].submission_uuid
                                answer, tmp_correctness = get_answer_and_correctness(user_state_dict, score,
                                                                                     item['category'],
                                                                                     item['data'],
                                                                                     key,
                                                                                     submission_uuid=submission_uuid)

                                if answer and item['category'] in question_categories:
                                    item['correctness'] = tmp_correctness

                                unix_timestamp = int(time.mktime(score.last_answer_timestamp.timetuple())) \
                                    if score.last_answer_timestamp else None
                                browser_datetime = _get_browser_datetime(score.last_answer_timestamp,
                                                                         timezone_offset) \
                                    if score.last_answer_timestamp else ''

                                od = OrderedDict(sorted(answer.items())) if answer else {}
                                answer = '; '.join(od.values()) if answer else None
                                if answer:
                                    answer = escape(answer)
                                resp['items'].append({
                                    'display_name': item['data'].display_name,
                                    'question_text': item['question_text'],
                                    'question_text_safe': item['question_text_safe'],
                                    'answer': answer,
                                    'question_description': '',
                                    'parent_name': item['parent_name'],
                                    'correctness': item['correctness'].title() if item['correctness'] else 'Not Answered',
                                    'earned': get_score_points(score.earned),
                                    'possible': get_score_points(score.possible),
                                    'last_answer_timestamp': score.last_answer_timestamp,
                                    'unix_timestamp': unix_timestamp,
                                    'browser_datetime': browser_datetime,
                                    'id': item['id']
                                })
    except Http404:
        resp['error'] = True

    return resp
