import json
from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404
from django.urls import reverse
from lms.djangoapps.courseware.utils import CREDO_GRADED_ITEM_CATEGORIES
from lms.djangoapps.courseware.models import StudentModule
from lti_provider.models import LtiContextId
from student.models import CourseEnrollment
from credo_modules.models import OrganizationTag, TagDescription, OraBlockScore, OraScoreType, Organization
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructureTags, BlockToSequential, \
    OraBlockStructure
from edxmako.shortcuts import render_to_response
from opaque_keys.edx.keys import UsageKey
from .extended_progress import get_tag_values, get_tags_summary_data, get_tag_title, get_tag_title_short,\
    convert_into_tree


MAX_COURSES_PER_USER = 50


class GradeInfo:
    points_earned = 0
    max_grade = 0
    answer = None
    question_text = None

    def __init__(self, points_earned=0, points_possible=0, answered=False, answer=None, question_text=None):
        self.points_earned = points_earned
        self.points_possible = points_possible
        self.answered = answered
        self.answer = answer
        self.question_text = question_text


def get_tags_global_data(student, orgs, course_ids, course_keys, group_tags=False, group_by_course=False):
    tags = {}
    blocks = {}

    org_tags = OrganizationTag.get_orgs_tags(orgs)
    tags_to_hide = [t.tag_name for t in org_tags if not t.progress_view]
    tag_descriptions = {t.tag_name: t.description for t in TagDescription.objects.all()}

    blocks_raw_data = BlockToSequential.objects.filter(
        course_id__in=course_ids, graded=1, deleted=False,
        visible_to_staff_only=False).values('block_id', 'sequential_id', 'sequential_name')
    for block in blocks_raw_data:
        blocks[block['block_id']] = {
            'sequential_name': block['sequential_name'],
            'sequential_id': block['sequential_id']
        }

    modules_raw_data = StudentModule.objects.filter(
        course_id__in=course_keys, module_type__in=CREDO_GRADED_ITEM_CATEGORIES,
        student=student).values('state', 'module_type', 'module_state_key', 'grade', 'max_grade')

    contexts = LtiContextId.objects.filter(
        course_key__in=course_keys, user=student).values('usage_key', 'properties')
    seq_block_to_course = {}
    for context in contexts:
        context_data = json.loads(context['properties'])
        if 'context_label' in context_data:
            seq_block_to_course[str(context['usage_key'])] = context_data['context_label']

    ora_empty_rubrics = []
    ora_ungraded = []
    grades_data = {}
    ora_grades_data = {}

    ora_grades = OraBlockScore.objects.filter(
        course_id__in=course_ids, score_type=OraScoreType.STAFF,
        user=student).values('block_id', 'criterion', 'points_earned')
    for ora_grade in ora_grades:
        if ora_grade['block_id'] not in ora_grades_data:
            ora_grades_data[ora_grade['block_id']] = {}
        ora_grades_data[ora_grade['block_id']][ora_grade['criterion'].strip()] = {
            'points_earned': ora_grade['points_earned']
        }

    ora_block_structure = OraBlockStructure.objects.filter(course_id__in=course_ids)
    for ora_block in ora_block_structure:
        steps = ora_block.get_steps()

        if ora_block.ungraded:
            if ora_block.block_id not in ora_ungraded:
                ora_ungraded.append(ora_block.block_id)
            continue

        if not ora_block.is_ora_empty_rubrics:
            if 'staff' in steps:
                grades_data[ora_block.block_id] = {}
                rubric_criteria = ora_block.get_rubric_criteria()
                for crit in rubric_criteria:
                    crit_label = crit['label'].strip()
                    points_possible = max([p['points'] for p in crit['options']])
                    points_earned = 0
                    if ora_block.block_id in ora_grades_data and crit_label in ora_grades_data[ora_block.block_id]:
                        points_earned = ora_grades_data[ora_block.block_id][crit_label]['points_earned']
                    grades_data[ora_block.block_id][crit_label] = GradeInfo(
                        points_earned=points_earned, points_possible=points_possible)
        else:
            ora_empty_rubrics.append(ora_block.block_id)
            grades_data[ora_block.block_id] = GradeInfo(points_possible=1)

    for item in modules_raw_data:
        block_id = str(item['module_state_key'])
        if block_id not in blocks:
            continue
        if item['module_type'] == 'openassessment':
            state_data = json.loads(item['state'])
            if 'submission_uuid' in state_data:
                if block_id in ora_empty_rubrics:
                    grades_data[block_id].points_possible = 1
                    grades_data[block_id].answered = True
                elif block_id in grades_data:
                    for crit_label, _ in grades_data[block_id].items():
                        grades_data[block_id][crit_label].answered = True
        else:
            answered = item['grade'] is not None
            points_possible = item['max_grade']
            points_earned = item['grade']
            if points_earned is None:
                points_earned = 0
            else:
                points_earned = int(points_earned)
            if points_possible is None:
                if item['module_type'] == 'problem':
                    item_state = json.loads(item['state'])
                    points_possible = int(item_state.get('score', {}).get('raw_possible', 0))
                else:
                    points_possible = 0
            else:
                points_possible = int(points_possible)

            grades_data[block_id] = GradeInfo(points_earned=points_earned, points_possible=points_possible,
                                              answered=answered)

    tags_raw_data = ApiCourseStructureTags.objects.filter(course_id__in=course_ids, is_parent=0)\
        .order_by('tag_value').values('block_id', 'rubric', 'tag_value')
    for tag in tags_raw_data:
        is_ora = bool(tag['rubric'])
        tag_block_id = str(tag['block_id'])
        if tag_block_id not in blocks:
            continue
        if is_ora and tag_block_id in ora_ungraded:
            continue
        section_id = blocks[tag_block_id]['sequential_id']
        sequential_name = blocks[tag_block_id]['sequential_name']
        tmp_tag_values = get_tag_values([tag['tag_value']], group_tags=group_tags, tags_to_hide=tags_to_hide,
                                        tag_descriptions=tag_descriptions)
        points_earned = 0
        points_possible = 1
        answered = False
        correctness = 'Not Answered'

        if tag_block_id in grades_data:
            grade_info = grades_data[tag_block_id][tag['rubric']] if is_ora else grades_data[tag_block_id]
            points_earned = grade_info.points_earned
            points_possible = grade_info.points_possible
            answered = grade_info.answered
            if points_earned == 0:
                correctness = 'incorrect'
            elif points_possible == points_earned:
                correctness = 'correct'
            else:
                correctness = 'partially correct'

        for tmp_tag in tmp_tag_values:
            tag_key = tmp_tag['value'].strip()
            if tag_key not in tags:
                tags[tag_key] = {
                    'tag': tag_key.strip(),
                    'tag_title': get_tag_title(tag_key),
                    'tag_title_short': get_tag_title_short(tag_key),
                    'tag_description': tmp_tag['description'],
                    'problems': [],
                    'courses_num': 0,
                    'problems_answered': [],
                    'courses': OrderedDict(),
                    'sections': {},
                    'answers': 0,
                    'tag_num': tmp_tag['num'],
                    'tag_is_last': tmp_tag['is_last'],
                    'id': tmp_tag['id'],
                    'parent_id': tmp_tag['parent_id'],
                    'children': []
                }

            course_label = seq_block_to_course.get(section_id)
            if not course_label:
                course_label = UsageKey.from_string(section_id).course
            if course_label not in tags[tag_key]['courses']:
                tags[tag_key]['courses_num'] += 1
                tags[tag_key]['courses'][course_label] = {'sections': {}}

            if section_id not in tags[tag_key]['sections']:
                tags[tag_key]['sections'][section_id] = {
                    'display_name': sequential_name,
                    'problems': []
                }

            if section_id not in tags[tag_key]['courses'][course_label]['sections']:
                tags[tag_key]['courses'][course_label]['sections'][section_id] = {
                    'display_name': sequential_name,
                    'problems': []
                }

            problem = {
                'problem_id': tag_block_id,
                'possible': points_possible,
                'earned': points_earned,
                'answered': answered,
                'answer': '',  # TODO
                'correctness': correctness.title(),
                'section_display_name': sequential_name,
                'section_id': section_id,
                'display_name': '',  # TODO
                'question_text': '',  # TODO
                'question_text_safe': '',  # TODO
                'hidden': False  # TODO
            }
            tags[tag_key]['problems'].append(problem)
            tags[tag_key]['sections'][section_id]['problems'].append(problem)
            tags[tag_key]['courses'][course_label]['sections'][section_id]['problems'].append(problem)

            if answered and tag_block_id not in tags[tag_key]['problems_answered']:
                tags[tag_key]['problems_answered'].append(tag_block_id)
                tags[tag_key]['answers'] = tags[tag_key]['answers'] + 1

    return get_tags_summary_data(tags, group_by_course=group_by_course)


def get_student_name(student):
    student_name = student.first_name + ' ' + student.last_name
    student_name = student_name.strip()
    if student_name:
        student_name = student_name + ' (' + student.email + ')'
    else:
        student_name = student.email
    return student_name


@login_required
def global_skills_page(request):
    user = request.user
    user_id = request.GET.get('user_id')
    org = request.GET.get('org')
    page = request.GET.get('page')
    additional_params = []
    student = user
    group_tags = False
    group_by_course = False

    if page == 'skills':
        group_tags = True
        group_by_course = True

    if user.is_superuser and user_id:
        student = User.objects.filter(id=user_id).first()
        if not student:
            raise Http404("Student not found")
        else:
            additional_params.append('user_id=' + user_id)
    else:
        user_id = None

    enrollments = CourseEnrollment.objects.filter(user=student, is_active=True)
    course_ids = []
    course_keys = []
    orgs = []

    for enroll in enrollments:
        orgs.append(enroll.course_id.org)

    orgs_access_extended_progress_page = [o.org for o in Organization.objects.filter(
        org__in=orgs, org_type__enable_extended_progress_page=True)
    ]
    if org:
        if org in orgs_access_extended_progress_page:
            additional_params.append('org=' + org)
        else:
            org = None

    orgs = []

    for enroll in enrollments:
        enroll_org = enroll.course_id.org
        if enroll_org in orgs_access_extended_progress_page and (not org or org == enroll_org):
            course_ids.append(str(enroll.course_id))
            course_keys.append(enroll.course_id)
            if enroll.course_id.org not in orgs:
                orgs.append(enroll.course_id.org)

    if len(course_ids) > MAX_COURSES_PER_USER and len(orgs) > 1 and not org:
        return render_to_response('courseware/extended_progress_choose_org.html', {
            'orgs': sorted(orgs),
            'current_url': reverse('global_skills') + (('?' + '&'.join(additional_params)) if additional_params else ''),
            'student_id': student.id,
            'student': student,
            'student_name': get_student_name(student)
        })

    context = {
        'course': None,
        'course_id': None,
        'assessments_display': False,
        'student_id': student.id,
        'student': student,
        'student_name': get_student_name(student),
        'current_url': reverse('global_skills'),
        'current_url_additional_params': '&'.join(additional_params) if additional_params else ''
    }

    tags = get_tags_global_data(student, orgs, course_ids, course_keys, group_tags=group_tags,
                                group_by_course=group_by_course)
    if page == 'skills':
        tags_assessments = [v.copy() for v in tags if v['tag_is_last']]
        tags = convert_into_tree(tags)
        tags_assessments = sorted(tags_assessments, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))
        context.update({
            'tags': tags,
            'tags_assessments': tags_assessments
        })
        return render_to_response('courseware/extended_progress_skills.html', context)
    else:
        tags_to_100 = sorted(tags, key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
        tags_from_100 = sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))
        context.update({
            'top5tags': tags_from_100[:5],
            'lowest5tags': tags_to_100[:5],
            'assessments': []
        })
        return render_to_response('courseware/extended_progress.html', context)
