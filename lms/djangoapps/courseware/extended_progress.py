import json

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from openassessment.assessment.api import staff as staff_api
from submissions.api import get_submissions
from student.models import anonymous_id_for_user
from xmodule.modulestore.django import modulestore


def _tag_title(tag):
    return tag.replace(' - ', ' > ').replace('"', '')


def tags_student_progress(course, student, problem_blocks, courseware_summary):
    anonymous_user_id = anonymous_id_for_user(student, course.id, save=False)

    items = {}
    for chapter in courseware_summary:
        for section in chapter['sections']:
            if section.graded:
                for key, score in section.problem_scores.items():
                    items[str(key)] = {
                        'possible': score.possible,
                        'earned': score.earned,
                        'answered': 1 if score.first_attempted else 0
                    }

    tags = {}
    tag_categories = ['learning_outcome', 'custom_outcome']

    for problem_block in problem_blocks:
        item_block_location = str(problem_block.location)
        if item_block_location in items:
            for aside in problem_block.runtime.get_asides(problem_block):
                if ((aside.scope_ids.block_type == 'tagging_aside'
                     and problem_block.category in ['problem', 'drag-and-drop-v2']) or
                    (aside.scope_ids.block_type == 'tagging_ora_aside'
                     and problem_block.category == 'openassessment'
                     and len(problem_block.rubric_criteria) == 0)):
                    for tag_key, tag_values in aside.saved_tags.items():
                        if tag_key in tag_categories:
                            for tag in tag_values:
                                tag_key = tag.strip()
                                if tag_key not in tags:
                                    tags[tag_key] = {
                                        'tag': tag_key.strip(),
                                        'tag_title': _tag_title(tag_key),
                                        'problems': [],
                                        'problems_answered': [],
                                        'answers': 0
                                    }
                                tags[tag_key]['problems'].append({
                                    'problem_id': item_block_location,
                                    'possible': items[item_block_location]['possible'],
                                    'earned': items[item_block_location]['earned'],
                                    'answered': items[item_block_location]['answered']
                                })
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
                        criterions[rub['name']] = {
                            'possible': 0,
                            'earned': 0,
                            'label': rub['label']
                        }
                        for opt in rub['options']:
                            if opt['points'] > criterions[rub['name']]['possible']:
                                criterions[rub['name']]['possible'] = opt['points']

                    student_item_dict = dict(
                        course_id=str(course.id),
                        student_id=anonymous_user_id,
                        item_id=item_block_location,
                        item_type='openassessment'
                    )
                    context = dict(**student_item_dict)
                    submissions = get_submissions(context)
                    if len(submissions) > 0:
                        submission_uuid = submissions[0]['uuid']
                        staff_assessment = staff_api.get_latest_staff_assessment(submission_uuid)
                        if staff_assessment:
                            for part in staff_assessment['parts']:
                                criterions[part['option']['criterion']['name']]['earned'] = part["option"]['points']

                    for criterion, tags_dict in aside.saved_tags.items():
                        if criterion in criterions:
                            for tag_key, tag_values in tags_dict.items():
                                if tag_key in tag_categories:
                                    for tag in tag_values:
                                        tag_k = tag.strip()
                                        if tag_k not in tags:
                                            tags[tag_k] = {
                                                'tag': tag_k,
                                                'tag_title': _tag_title(tag_k),
                                                'problems': [],
                                                'problems_answered': [],
                                                'answers': 0
                                            }
                                        tags[tag_k]['problems'].append({
                                            'problem_id': item_block_location,
                                            'criterion': criterions[criterion]['label'],
                                            'possible': criterions[criterion]['possible'],
                                            'earned': criterions[criterion]['earned'],
                                            'answered': items[item_block_location]['answered']
                                        })
                                        if items[item_block_location]['answered'] \
                                                and item_block_location not in tags[tag_k]['problems_answered']:
                                            tags[tag_k]['problems_answered'].append(item_block_location)
                                            tags[tag_k]['answers'] = tags[tag_k]['answers'] \
                                                                   + items[item_block_location]['answered']

    for tag_k, tag_v in tags.items():
        num_questions = len(tag_v['problems'])
        percent_correct = int((sum([x['earned'] / x['possible'] for x in tag_v['problems']]) / num_questions) * 100)
        tags[tag_k]['num_questions'] = num_questions
        tags[tag_k]['percent_correct'] = percent_correct
    tags_result = sorted(tags.values(), key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
    return tags_result


def assessments_progress(courseware_summary):
    data = []
    percent_correct_sections_lst = []
    total_grade_lst = []
    total_num_questions = 0
    total_assessments = 0
    completed_assessments = 0
    not_started_assessments = 0

    for chapter in courseware_summary:
        for section in chapter['sections']:
            if section.graded:
                total_assessments = total_assessments + 1
                num_questions = len(section.problem_scores)
                percent_correct_tmp_lst = []
                completed_lst = []
                not_started_lst = []
                num_correct_lst = []

                for key, score in section.problem_scores.items():
                    percent_correct_tmp_lst.append(score.earned / score.possible)
                    completed_lst.append(score.first_attempted is not None)
                    not_started_lst.append(score.first_attempted is None)
                    num_correct_lst.append(1 if score.possible == score.earned else 0)
                    total_grade_lst.append({
                        'earned': score.earned,
                        'possible': score.possible
                    })
                    total_num_questions = total_num_questions + 1

                percent_correct = int((sum(percent_correct_tmp_lst) / num_questions) * 100)
                percent_correct_sections_lst.append(percent_correct)

                is_completed = all(completed_lst)
                is_not_started = all(not_started_lst)
                num_correct = sum(num_correct_lst)

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
    total_grade = int((sum([val['earned'] / val['possible'] for val in total_grade_lst]) / total_num_questions) * 100)
    return {
        'data': data,
        'data_str': json.dumps(data),
        'total_grade': total_grade,
        'best_grade': max(percent_correct_sections_lst),
        'lowest_grade': min(percent_correct_sections_lst),
        'total_assessments': total_assessments,
        'completed_assessments': completed_assessments,
        'not_started_assessments': not_started_assessments
    }


def progress_main_page(request, course, student):
    tagged_categories = ['problem', 'openassessment', 'drag-and-drop-v2']
    problem_blocks = modulestore().get_items(course.id, qualifiers={'category': {'$in': tagged_categories}})

    course_grade = CourseGradeFactory().read(student, course)
    courseware_summary = course_grade.chapter_grades.values()

    tags = tags_student_progress(course, student, problem_blocks, courseware_summary)
    assessments = assessments_progress(courseware_summary)

    context = {
        'top5tags': tags[-5:][::-1],
        'lowest5tags': tags[:5],
        'assessments': assessments
    }
    return context
