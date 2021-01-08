import json
from collections import OrderedDict

from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.views.decorators.http import require_POST
from django.http import Http404
from django.urls import reverse
from lms.djangoapps.courseware.module_render import get_module_by_usage_id
from lms.djangoapps.courseware.models import StudentModule
from lms.djangoapps.courseware.user_state_client import DjangoXBlockUserStateClient
from lms.djangoapps.courseware.utils import CREDO_GRADED_ITEM_CATEGORIES, get_block_children, \
    get_score_points, get_answer_and_correctness
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lti_provider.models import LtiContextId
from student.models import CourseEnrollment, anonymous_id_for_user
from credo_modules.models import OrganizationTag, TagDescription, OraBlockScore, OraScoreType, Organization
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructure, ApiCourseStructureTags, \
    BlockToSequential, OraBlockStructure
from edxmako.shortcuts import render_to_response
from opaque_keys.edx.keys import UsageKey, CourseKey
from xmodule.modulestore.django import modulestore
from .extended_progress import get_tag_values, get_tags_summary_data, get_tag_title, get_tag_title_short,\
    convert_into_tree, get_ora_submission_id


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


def get_tags_global_data(student, orgs, course_ids, tag_value=None, group_tags=False, group_by_course=False):
    tags = {}
    blocks = {}
    tags_to_hide = []
    tag_descriptions = {}

    if tag_value:
        tags_raw_data = ApiCourseStructureTags.objects.filter(course_id__in=course_ids, is_parent=0,
                                                              tag_value=tag_value) \
            .order_by('tag_value').values('course_id', 'block_id', 'rubric', 'tag_value')
        tag_course_ids = []
        for tmp_tag_item in tags_raw_data:
            if tmp_tag_item['course_id'] not in tag_course_ids:
                tag_course_ids.append(tmp_tag_item['course_id'])
        for course_id in course_ids:
            if course_id not in tag_course_ids:
                course_ids.remove(course_id)
    else:
        tags_raw_data = ApiCourseStructureTags.objects.filter(course_id__in=course_ids, is_parent=0)\
            .order_by('tag_value').values('block_id', 'rubric', 'tag_value')

    org_tags = OrganizationTag.get_orgs_tags(orgs)
    course_keys = [CourseKey.from_string(ci) for ci in course_ids]

    if not tag_value:
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
        if context['properties']:
            context_data = json.loads(context['properties'])
            if 'context_label' in context_data:
                seq_block_to_course[str(context['usage_key'])] = context_data['context_label']

    ora_empty_rubrics = []
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

    ora_block_structure = OraBlockStructure.objects.filter(
        course_id__in=course_ids, ungraded=False)
    for ora_block in ora_block_structure:
        steps = ora_block.get_steps()

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

    for tag in tags_raw_data:
        is_ora = bool(tag['rubric'])
        tag_block_id = str(tag['block_id'])
        if tag_block_id not in blocks:
            continue
        if is_ora and tag_block_id not in grades_data:
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
                    'problems': [],
                    'section_id': section_id
                }

            if section_id not in tags[tag_key]['courses'][course_label]['sections']:
                tags[tag_key]['courses'][course_label]['sections'][section_id] = {
                    'display_name': sequential_name,
                    'problems': [],
                    'section_id': section_id
                }

            problem = {
                'problem_id': tag_block_id,
                'possible': points_possible,
                'earned': points_earned,
                'answered': answered,
                'correctness': correctness.title(),
                'section_display_name': sequential_name,
                'section_id': section_id
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


def _get_global_skills_context(request, user_id, org):
    user = request.user
    additional_params = []
    student = user

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
    orgs = []

    for enroll in enrollments:
        if enroll.course_id.org not in orgs:
            orgs.append(enroll.course_id.org)

    orgs_access_extended_progress_page = [o.org for o in Organization.objects.filter(
        org__in=orgs, org_type__enable_extended_progress_page=True)]
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
            if enroll.course_id.org not in orgs:
                orgs.append(enroll.course_id.org)

    return user_id, student, course_ids, orgs, org, additional_params


@login_required
def global_skills_page(request):
    user_id = request.GET.get('user_id')
    org = request.GET.get('org')
    page = request.GET.get('page')
    group_tags = False

    if page == 'skills':
        group_tags = True

    user_id, student, course_ids, orgs, org, additional_params = _get_global_skills_context(request, user_id, org)

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
        'url_api_get_tag_data': reverse('global_skills_api_get_tag_data'),
        'url_api_get_tag_section_data': reverse('global_skills_api_get_tag_section_data'),
        'api_student_id': student.id,
        'api_org': org,
        'current_url_additional_params': '&'.join(additional_params) if additional_params else ''
    }

    tags = get_tags_global_data(student, orgs, course_ids, group_tags=group_tags)
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


def get_sequential_block_questions(request, section_id, tag_value, student):
    usage_key = UsageKey.from_string(section_id)
    course_key = usage_key.course_key
    course_id = str(course_key)
    block_ids = {}

    anonymous_user_id = anonymous_id_for_user(student, course_key, save=False)
    seq_block_cache = ApiCourseStructure.objects.filter(
        block_id=section_id, course_id=course_id, graded=1, deleted=False).first()
    if not seq_block_cache:
        return

    with modulestore().bulk_operations(course_key):
        course = modulestore().get_course(course_key, depth=0)
        seq_block, _ = get_module_by_usage_id(request, course_id, section_id)

        course_grade = CourseGradeFactory().read(student, course)
        courseware_summary = course_grade.chapter_grades.values()
        children_dict = get_block_children(seq_block, seq_block_cache.display_name)

    tags_raw_data = ApiCourseStructureTags.objects.filter(course_id=course_id, tag_value=tag_value)\
        .order_by('tag_value', 'rubric').values('block_id', 'rubric')
    for tag in tags_raw_data:
        is_ora = bool(tag['rubric'])
        if tag['block_id'] not in block_ids:
            block_ids[tag['block_id']] = {
                'is_ora': is_ora,
                'rubrics': []
            }
        block_ids[tag['block_id']]['rubrics'].append(tag['rubric'])

    user_state_client = DjangoXBlockUserStateClient(student)
    user_state_dict = {}
    if block_ids:
        user_state_dict = user_state_client.get_all_blocks(student, course_key, list(block_ids.keys()))

    items = []
    ora_blocks = {}
    ora_grades_data = {}
    ora_empty_rubrics = []

    ora_block_structure = OraBlockStructure.objects.filter(
        block_id__in=list(block_ids.keys()), ungraded=False, display_rubric_step_to_students=True)
    for ora_block in ora_block_structure:
        ora_blocks[ora_block.block_id] = ora_block
        if ora_block.is_ora_empty_rubrics:
            ora_empty_rubrics.append(ora_block.block_id)

    ora_grades = OraBlockScore.objects.filter(
        block_id__in=list(block_ids.keys()), user=student, score_type=OraScoreType.STAFF)
    for ora_grade in ora_grades:
        if ora_grade.block_id not in ora_grades_data:
            ora_grades_data[ora_grade.block_id] = {}
        ora_grades_data[ora_grade.block_id][ora_grade.criterion.strip()] = {
            'points_earned': ora_grade.points_earned,
            'answer': ora_grade.answer
        }

    for chapter in courseware_summary:
        for section in chapter['sections']:
            if section.graded and str(section.location) == section_id:
                for key, score in section.problem_scores.items():
                    item_block_location = str(key)
                    if item_block_location in block_ids:
                        block_info = block_ids[item_block_location]
                        problem_detailed_info = children_dict.get(item_block_location)
                        problem_block = problem_detailed_info['data']

                        submission_uuid = None
                        if item_block_location in ora_empty_rubrics:
                            submission = get_ora_submission_id(course.id, anonymous_user_id, item_block_location)
                            if submission:
                                submission_uuid = submission['uuid']

                        answer, tmp_correctness = get_answer_and_correctness(
                            user_state_dict, score, problem_block.category, problem_block,
                            problem_block.location, submission_uuid=submission_uuid)

                        if not block_info['is_ora'] or item_block_location in ora_empty_rubrics:
                            od = OrderedDict(sorted(answer.items())) if answer else {}
                            items.append({
                                'problem_id': item_block_location,
                                'possible': get_score_points(score.possible),
                                'earned': get_score_points(score.earned),
                                'answered': 1 if score.first_attempted else 0,
                                'answer': '; '.join(od.values()) if answer else None,
                                'correctness': tmp_correctness.title() if tmp_correctness else 'Not Answered',
                                'display_name': problem_block.display_name,
                                'question_text': problem_detailed_info['question_text'],
                                'question_text_safe': problem_detailed_info['question_text_safe'],
                            })
                        else:
                            ora_block = ora_blocks.get(item_block_location)
                            rubric_criteria = ora_block.get_rubric_criteria()
                            crit_to_points_possible = {}
                            for crit in rubric_criteria:
                                crit_label = crit['label'].strip()
                                points_possible = max([p['points'] for p in crit['options']])
                                crit_to_points_possible[crit_label] = points_possible
                            if ora_block:
                                for rubric in block_info['rubrics']:
                                    if rubric not in crit_to_points_possible:
                                        continue
                                    ora_grades_dict = ora_grades_data.get(item_block_location, {}).get(rubric, {})
                                    points_earned = ora_grades_dict.get('points_earned', 0)
                                    points_possible = crit_to_points_possible.get(rubric, 0)
                                    if points_possible == 0:
                                        continue
                                    ora_answer = ora_grades_dict.get('answer')
                                    if points_earned == 0:
                                        criterion_correctness = 'incorrect'
                                    elif points_possible == points_earned:
                                        criterion_correctness = 'correct'
                                    else:
                                        criterion_correctness = 'partially correct'

                                    items.append({
                                        'problem_id': item_block_location,
                                        'criterion': rubric,
                                        'possible': get_score_points(points_possible),
                                        'earned': get_score_points(points_earned),
                                        'answered': 1 if ora_answer else 0,
                                        'answer': ora_answer,
                                        'correctness': criterion_correctness.title() if tmp_correctness else 'Not Answered',
                                        'display_name': problem_block.display_name + ': ' + rubric.title(),
                                        'question_text': problem_detailed_info['question_text'],
                                        'question_text_safe': problem_detailed_info['question_text_safe'],
                                    })
    return items


@login_required
@require_POST
def api_get_global_tag_data(request):
    user_id = request.POST.get('student_id')
    org = request.POST.get('org')
    tag_value = request.POST.get('tag')
    if not tag_value:
        raise Http404

    user_id, student, course_ids, orgs, org, additional_params = _get_global_skills_context(request, user_id, org)
    tags = get_tags_global_data(student, orgs, course_ids, tag_value=tag_value, group_tags=False, group_by_course=True)

    return render_to_response('courseware/extended_progress_skills_tag_block.html', {
        'tag': list(tags)[0] if len(tags) else None
    })


@login_required
@require_POST
def api_get_global_tag_section_data(request):
    user_id = request.POST.get('student_id')
    org = request.POST.get('org')
    tag_value = request.POST.get('tag')
    section_id = request.POST.get('section_id')
    if not tag_value or not section_id:
        raise Http404

    user_id, student, course_ids, orgs, org, additional_params = _get_global_skills_context(request, user_id, org)
    items = get_sequential_block_questions(request, section_id, tag_value, student)

    return render_to_response('courseware/extended_progress_skills_tag_section_block.html', {
        'items': items
    })
