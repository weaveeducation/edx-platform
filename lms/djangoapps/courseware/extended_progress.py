import json
from collections import OrderedDict

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.courseware.utils import get_problem_detailed_info, get_answer_and_correctness, get_score_points,\
    CREDO_GRADED_ITEM_CATEGORIES
from lms.djangoapps.courseware.user_state_client import DjangoXBlockUserStateClient
from openassessment.assessment.api import staff as staff_api
from submissions.api import get_submissions
from student.models import anonymous_id_for_user
from xmodule.modulestore.django import modulestore
from credo_modules.models import OrganizationTag, TagDescription


def get_tag_title(tag):
    tag_parts = tag.split(' - ')
    if len(tag_parts) > 1:
        return ' > '.join(tag_parts[1:]).replace('"', '')
    else:
        return tag.replace('"', '')


def get_tag_title_short(tag):
    tag_parts = tag.split(' - ')
    if len(tag_parts) > 1:
        return tag_parts[-1].replace('"', '')
    else:
        return tag.replace('"', '')


def get_ora_submission_id(course_id, anonymous_user_id, block_id):
    student_item_dict = dict(
        course_id=str(course_id),
        student_id=anonymous_user_id,
        item_id=block_id,
        item_type='openassessment'
    )
    context = dict(**student_item_dict)
    submissions = get_submissions(context)
    if len(submissions) > 0:
        return submissions[0]
    return None


def get_tag_values(data, group_tags=False, tags_to_hide=None, tag_descriptions=None):
    res = []
    tags_used = []
    if not tags_to_hide:
        tags_to_hide = []
    if not tag_descriptions:
        tag_descriptions = {}

    if group_tags:
        for v in data:
            if v.startswith(tuple(tags_to_hide)):
                continue
            tag_split_lst = v.split(' - ')
            if len(tag_split_lst) > 1:
                for idx, tag_part in enumerate(tag_split_lst):
                    if idx > 0:
                        tag_new_val = ' - '.join(tag_split_lst[0:idx + 1])
                        if tag_new_val not in tags_used:
                            res.append({
                                'value': tag_new_val,
                                'num': idx - 1,
                                'is_last': (idx == (len(tag_split_lst) - 1)),
                                'id': tag_new_val,
                                'parent_id': ' - '.join(tag_split_lst[0:idx]) if idx > 1 else None,
                                'description': tag_descriptions.get(tag_new_val, '').replace('\n', ' ').replace('\r', '')
                            })
                            tags_used.append(tag_new_val)
            else:
                res.append({
                    'value': v,
                    'num': 0,
                    'is_last': True,
                    'id': v,
                    'parent_id': None,
                    'description': tag_descriptions.get(v, '').replace('\n', ' ').replace('\r', '')
                })
        return res
    else:
        for v in data:
            if v.startswith(tuple(tags_to_hide)):
                continue
            res.append({
                'value': v,
                'num': 0,
                'is_last': True,
                'id': v,
                'parent_id': None,
                'description': tag_descriptions.get(v, '').replace('\n', ' ').replace('\r', '')
            })
        return res


def _convert_into_tree_filter(_d):
    return {a: b for a, b in _d.items() if a != 'parent_id'}


def _sort_tree_node(tags):
    return sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag_title_short']))


def convert_into_tree(_d, _start=None):
    res = []
    for i in _d:
        if i['parent_id'] == _start:
            p = i.copy()
            p['children'] = convert_into_tree(_d, i['id'])
            res.append(_convert_into_tree_filter(p))
    return _sort_tree_node(res)


def tags_student_progress(course, student, problem_blocks, courseware_summary, group_tags=False):
    anonymous_user_id = anonymous_id_for_user(student, course.id, save=False)
    tag_descriptions = {t.tag_name: t.description for t in TagDescription.objects.all()}

    items = OrderedDict()
    for chapter in courseware_summary:
        for section in chapter['sections']:
            if section.graded:
                for key, score in section.problem_scores.items():
                    items[str(key)] = {
                        'score': score,
                        'possible': score.possible,
                        'earned': score.earned,
                        'answered': 1 if score.first_attempted else 0,
                        'section_display_name': section.display_name,
                        'section_id': str(section.location)
                    }

    tags = {}
    #tag_categories = ['learning_outcome', 'custom_outcome']
    tag_categories = '*'

    org_tags = OrganizationTag.get_org_tags(course.id.org)
    tags_to_hide = [t.tag_name for t in org_tags if not t.progress_view]

    problem_locations = [problem_block.location for problem_block in problem_blocks]
    problem_locations_dict = {str(problem_block.location): problem_block for problem_block in problem_blocks}
    user_state_client = DjangoXBlockUserStateClient(student)
    user_state_dict = {}
    if problem_locations:
        user_state_dict = user_state_client.get_all_blocks(student, course.id, problem_locations)

    for item_block_location in items:
        section_id = items[item_block_location]['section_id']
        if item_block_location in problem_locations_dict:
            problem_block = problem_locations_dict[item_block_location]
            problem_detailed_info = get_problem_detailed_info(problem_block, None, add_correctness=False)

            submission_uuid = None
            submission = None
            if problem_block.category == 'openassessment':
                submission = get_ora_submission_id(course.id, anonymous_user_id, item_block_location)
                if submission:
                    submission_uuid = submission['uuid']

            answer, tmp_correctness = get_answer_and_correctness(user_state_dict, items[item_block_location]['score'],
                                                                 problem_block.category, problem_block,
                                                                 problem_block.location, submission=submission)
            od = OrderedDict(sorted(answer.items())) if answer else {}

            for aside in problem_block.runtime.get_asides(problem_block):
                if ((aside.scope_ids.block_type == 'tagging_aside'
                     and problem_block.category in ['problem', 'image-explorer', 'drag-and-drop-v2']) or
                    (aside.scope_ids.block_type == 'tagging_ora_aside'
                     and problem_block.category == 'openassessment'
                     and len(problem_block.rubric_criteria) == 0)):
                    for tag_cat, tag_values in aside.saved_tags.items():
                        if tag_categories == '*' or tag_cat in tag_categories:
                            tmp_tag_values = get_tag_values(tag_values, group_tags=group_tags,
                                                            tags_to_hide=tags_to_hide,
                                                            tag_descriptions=tag_descriptions)
                            for tag in tmp_tag_values:
                                tag_key = tag['value'].strip()
                                if tag_key not in tags:
                                    tags[tag_key] = {
                                        'tag': tag_key.strip(),
                                        'tag_title': get_tag_title(tag_key),
                                        'tag_title_short': get_tag_title_short(tag_key),
                                        'tag_description': tag['description'],
                                        'problems': [],
                                        'courses_num': 0,
                                        'problems_answered': [],
                                        'sections': {},
                                        'answers': 0,
                                        'tag_num': tag['num'],
                                        'tag_is_last': tag['is_last'],
                                        'id': tag['id'],
                                        'parent_id': tag['parent_id'],
                                        'children': []
                                    }
                                if section_id not in tags[tag_key]['sections']:
                                    tags[tag_key]['sections'][section_id] = {
                                        'display_name': items[item_block_location]['section_display_name'],
                                        'problems': [],
                                        'section_id': section_id
                                    }
                                problem = {
                                    'problem_id': item_block_location,
                                    'possible': get_score_points(items[item_block_location]['possible']),
                                    'earned': get_score_points(items[item_block_location]['earned']),
                                    'answered': items[item_block_location]['answered'],
                                    'answer': '; '.join(od.values()) if answer else None,
                                    'correctness': tmp_correctness.title() if tmp_correctness else 'Not Answered',
                                    'section_display_name': items[item_block_location]['section_display_name'],
                                    'section_id': section_id,
                                    'display_name': problem_block.display_name,
                                    'question_text': problem_detailed_info['question_text'],
                                    'question_text_safe': problem_detailed_info['question_text_safe'],
                                    'hidden': problem_detailed_info['hidden']
                                }
                                tags[tag_key]['problems'].append(problem)
                                tags[tag_key]['sections'][section_id]['problems'].append(problem)
                                if items[item_block_location]['answered'] \
                                        and item_block_location not in tags[tag_key]['problems_answered']:
                                    tags[tag_key]['problems_answered'].append(item_block_location)
                                    tags[tag_key]['answers'] = tags[tag_key]['answers']\
                                                               + items[item_block_location]['answered']
                elif aside.scope_ids.block_type == 'tagging_ora_aside' \
                  and len(aside.saved_tags) > 0 \
                  and problem_block.category == 'openassessment' \
                  and len(problem_block.rubric_criteria) > 0 \
                  and "staff-assessment" in problem_block.assessment_steps:
                    criterions = {}
                    for rub in problem_block.rubric_criteria:
                        criterions[rub['label'].strip()] = {
                            'possible': 0,
                            'earned': 0,
                            'label': rub['label'].strip(),
                            'name': rub['name'].strip()
                        }
                        for opt in rub['options']:
                            if opt['points'] > criterions[rub['label'].strip()]['possible']:
                                criterions[rub['label'].strip()]['possible'] = opt['points']

                    if submission_uuid:
                        staff_assessment = staff_api.get_latest_staff_assessment(submission_uuid)
                        if staff_assessment:
                            for part in staff_assessment['parts']:
                                criterions[part['option']['criterion']['label'].strip()]['earned'] = part["option"]['points']

                    for criterion, tags_dict in aside.saved_tags.items():
                        if criterion in criterions:
                            for tag_cat, tag_values in tags_dict.items():
                                if tag_categories == '*' or tag_cat in tag_categories:
                                    tmp_tag_values = get_tag_values(tag_values, group_tags=group_tags,
                                                                    tags_to_hide=tags_to_hide,
                                                                    tag_descriptions=tag_descriptions)
                                    for tag in tmp_tag_values:
                                        tag_k = tag['value'].strip()
                                        if tag_k not in tags:
                                            tags[tag_k] = {
                                                'tag': tag_k,
                                                'tag_title': get_tag_title(tag_k),
                                                'tag_title_short': get_tag_title_short(tag_k),
                                                'tag_description': tag['description'],
                                                'problems': [],
                                                'courses_num': 0,
                                                'problems_answered': [],
                                                'sections': {},
                                                'answers': 0,
                                                'tag_num': tag['num'],
                                                'tag_is_last': tag['is_last'],
                                                'id': tag['id'],
                                                'parent_id': tag['parent_id'],
                                                'children': []
                                            }
                                        if section_id not in tags[tag_k]['sections']:
                                            tags[tag_k]['sections'][section_id] = {
                                                'display_name': items[item_block_location]['section_display_name'],
                                                'problems': [],
                                                'section_id': section_id
                                            }

                                        if criterions[criterion]['earned'] == 0:
                                            criterion_correctness = 'incorrect'
                                        elif criterions[criterion]['possible'] == criterions[criterion]['earned']:
                                            criterion_correctness = 'correct'
                                        else:
                                            criterion_correctness = 'partially correct'

                                        problem = {
                                            'problem_id': item_block_location,
                                            'criterion': criterions[criterion]['label'],
                                            'possible': get_score_points(criterions[criterion]['possible']),
                                            'earned': get_score_points(criterions[criterion]['earned']),
                                            'answered': items[item_block_location]['answered'],
                                            'answer': '; '.join(od.values()) if answer else None,
                                            'correctness': criterion_correctness.title() if tmp_correctness else 'Not Answered',
                                            'section_display_name': items[item_block_location]['section_display_name'],
                                            'section_id': items[item_block_location]['section_id'],
                                            'display_name': problem_block.display_name + ': ' + criterion,
                                            'question_text': problem_detailed_info['question_text'],
                                            'question_text_safe': problem_detailed_info['question_text_safe'],
                                            'hidden': problem_detailed_info['hidden']
                                        }
                                        tags[tag_k]['problems'].append(problem)
                                        tags[tag_k]['sections'][section_id]['problems'].append(problem)
                                        if items[item_block_location]['answered'] \
                                                and item_block_location not in tags[tag_k]['problems_answered']:
                                            tags[tag_k]['problems_answered'].append(item_block_location)
                                            tags[tag_k]['answers'] = tags[tag_k]['answers'] \
                                                                   + items[item_block_location]['answered']

    return get_tags_summary_data(tags)


def get_tags_summary_data(tags, group_by_course=False):
    for tag_k, tag_v in tags.items():
        num_questions = len(tag_v['problems'])
        if num_questions > 0:
            percent_correct = int((sum([(x['earned'] * 1.0) / (x['possible'] * 1.0) for x in tag_v['problems'] if x['possible'] > 0]) / num_questions) * 100)
        else:
            percent_correct = 0
        tags[tag_k]['num_questions'] = num_questions
        tags[tag_k]['percent_correct'] = percent_correct

        if group_by_course:
            for course_label, course_data in tags[tag_k]['courses'].items():
                sections = []
                for section_id, section_val in course_data['sections'].items():
                    _process_tag_section_info(section_val, sections)
                tags[tag_k]['courses'][course_label]['sections'] = sorted(
                    sections, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['display_name']))
            tags[tag_k]['courses'] = OrderedDict(sorted(tags[tag_k]['courses'].items()))
        else:
            sections = []
            for section_id, section_val in tags[tag_k]['sections'].items():
                _process_tag_section_info(section_val, sections)
            tags[tag_k]['sections'] = sorted(sections, key=lambda k: "%03d_%s" % (100 - k['percent_correct'],
                                                                                  k['display_name']))
    return tags.values()


def _process_tag_section_info(section_val, sections):
    section_num_questions = len(section_val['problems'])
    if section_num_questions > 0:
        section_percent_correct = int((sum(
            [(x['earned'] * 1.0) / (x['possible'] * 1.0) for x in section_val['problems'] if
             x['possible'] > 0]) / section_num_questions) * 100)
    else:
        section_percent_correct = 0

    unique_lst_of_questions = []
    section_answers_sum = 0
    for pr in section_val['problems']:
        if pr['problem_id'] not in unique_lst_of_questions and pr['answered']:
            unique_lst_of_questions.append(pr['problem_id'])
            section_answers_sum = section_answers_sum + pr['answered']

    section_val['answers'] = section_answers_sum
    section_val['num_questions'] = section_num_questions
    section_val['percent_correct'] = section_percent_correct
    sections.append(section_val)


def assessments_progress(courseware_summary, problems_dict=None):
    data = []
    percent_correct_sections_lst = []
    total_grade_lst = []
    total_num_questions = 0
    total_assessments = 0
    completed_assessments = 0
    not_started_assessments = 0
    course_tree = []

    for chapter in courseware_summary:
        chapter_data = {
            'display_name': chapter['display_name'],
            'sequential_blocks': []
        }
        for section in chapter['sections']:
            if section.graded:
                sequential_block = {
                    'display_name': section.display_name,
                    'vertical_blocks': []
                }
                total_assessments = total_assessments + 1
                num_questions = 0
                num_questions_calculate = 0
                num_questions_answered = 0
                percent_correct_tmp_lst = []
                completed_lst = []
                not_started_lst = []
                num_correct_lst = []
                num_incorrect_lst = []
                verticals = OrderedDict()

                for key, score in section.problem_scores.items():
                    if score.possible > 0:
                        percent_correct_tmp_lst.append((1.0 * score.earned) / (1.0 * score.possible))
                        num_questions_calculate = num_questions_calculate + 1
                    num_questions = num_questions + 1

                    completed_lst.append(score.first_attempted is not None)
                    not_started_lst.append(score.first_attempted is None)
                    if score.first_attempted is not None:
                        num_questions_answered = num_questions_answered + 1
                        if score.possible == score.earned:
                            num_correct_lst.append(1)
                        else:
                            num_incorrect_lst.append(1)

                    total_grade_lst.append({
                        'earned': get_score_points(score.earned),
                        'possible': get_score_points(score.possible)
                    })

                    if score.possible > 0:
                        total_num_questions = total_num_questions + 1

                    if problems_dict is not None:
                        key_str = str(key)
                        if key_str in problems_dict and not problems_dict[key_str]['hidden']:
                            vertical_id = problems_dict[key_str]['vertical_id']
                            vertical_name = problems_dict[key_str]['vertical_name']
                            problem_display_name = problems_dict[key_str]['display_name']
                            if vertical_id not in verticals:
                                verticals[vertical_id] = {
                                    'display_name': vertical_name,
                                    'vertical_id': vertical_id,
                                    'elements': []
                                }
                            current_elements_num = len(verticals[vertical_id]['elements'])
                            verticals[vertical_id]['elements'].append({
                                'not_started': score.first_attempted is None,
                                'is_correct': 1 if score.possible == score.earned and score.first_attempted is not None else 0,
                                'problem_id': key_str,
                                'num': str(current_elements_num + 1),
                                'display_name': problem_display_name
                            })

                percent_correct = 0
                if num_questions_calculate:
                    percent_correct = int((sum(percent_correct_tmp_lst) / (num_questions_calculate * 1.0)) * 100)
                percent_correct_sections_lst.append(percent_correct)

                is_completed = all(completed_lst)
                is_not_started = all(not_started_lst)
                num_correct = sum(num_correct_lst)
                num_incorrect = sum(num_incorrect_lst)
                num_not_started_lst = sum(not_started_lst)

                percent_completed = 0
                if num_questions_calculate:
                    percent_completed = int((num_questions_answered / (num_questions * 1.0)) * 100)

                if is_completed:
                    completed_assessments = completed_assessments + 1
                if is_not_started:
                    not_started_assessments = not_started_assessments + 1

                data.append({
                    'title': section.display_name,
                    'percent_correct': percent_correct,
                    'correct': num_correct,
                    'total': num_questions,
                    'is_completed': is_completed,
                    'is_not_started': is_not_started
                })

                sequential_block.update({
                    'total': num_questions,
                    'correct': num_correct,
                    'incorrect': num_incorrect,
                    'unanswered': num_not_started_lst,
                    'percent_correct': percent_correct,
                    'percent_completed': percent_completed
                })

                sequential_block['vertical_blocks'] = list(verticals.values())
                chapter_data['sequential_blocks'].append(sequential_block)
        course_tree.append(chapter_data)

    total_grade = 0
    if total_num_questions > 0:
        total_grade = int((sum([(val['earned'] * 1.0) / (val['possible'] * 1.0) for val in total_grade_lst if val['possible'] > 0]) / total_num_questions) * 100)

    return {
        'data': data,
        'data_str': json.dumps(data),
        'total_grade': total_grade,
        'best_grade': max(percent_correct_sections_lst) if percent_correct_sections_lst else 0,
        'lowest_grade': min(percent_correct_sections_lst) if percent_correct_sections_lst else 0,
        'total_assessments': total_assessments,
        'completed_assessments': completed_assessments,
        'not_started_assessments': not_started_assessments,
        'course_tree': course_tree
    }


def progress_main_page(request, course, student):
    problem_blocks = modulestore().get_items(course.id, qualifiers={'category': {'$in': CREDO_GRADED_ITEM_CATEGORIES}})

    course_grade = CourseGradeFactory().read(student, course)
    courseware_summary = course_grade.chapter_grades.values()

    tags = tags_student_progress(course, student, problem_blocks, courseware_summary)
    assessments = assessments_progress(courseware_summary)

    tags_to_100 = sorted(tags, key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
    tags_from_100 = sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))

    context = {
        'top5tags': tags_from_100[:5],
        'lowest5tags': tags_to_100[:5],
        'assessments': assessments
    }
    return context


def progress_skills_page(request, course, student):
    problem_blocks = modulestore().get_items(course.id, qualifiers={'category': {'$in': CREDO_GRADED_ITEM_CATEGORIES}})

    course_grade = CourseGradeFactory().read(student, course)
    courseware_summary = course_grade.chapter_grades.values()

    tags = tags_student_progress(course, student, problem_blocks, courseware_summary, group_tags=True)
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


def progress_grades_page(request, course, student):
    problems_dict = {}
    problem_blocks = modulestore().get_items(course.id, qualifiers={'category': {'$in': CREDO_GRADED_ITEM_CATEGORIES}})
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

    course_grade = CourseGradeFactory().read(student, course)
    courseware_summary = course_grade.chapter_grades.values()

    assessments = assessments_progress(courseware_summary, problems_dict)

    context = {
        'assessments': assessments
    }
    return context
