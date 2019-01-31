from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from openassessment.assessment.api import staff as staff_api
from submissions.api import get_submissions
from student.models import anonymous_id_for_user
from xmodule.modulestore.django import modulestore


def tags_student_progress(course, student):
    course_grade = CourseGradeFactory().read(student, course)
    courseware_summary = course_grade.chapter_grades.values()
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
    tagged_categories = ['problem', 'openassessment', 'drag-and-drop-v2']
    tag_categories = ['learning_outcome', 'custom_outcome']

    problem_blocks = modulestore().get_items(course.id, qualifiers={'category': {'$in': tagged_categories}})
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
                                if tag not in tags:
                                    tags[tag] = {
                                        'tag': tag,
                                        'problems': [],
                                        'problems_answered': [],
                                        'answers': 0
                                    }
                                tags[tag]['problems'].append({
                                    'problem_id': item_block_location,
                                    'possible': items[item_block_location]['possible'],
                                    'earned': items[item_block_location]['earned'],
                                    'answered': items[item_block_location]['answered']
                                })
                                if items[item_block_location]['answered'] \
                                        and item_block_location not in tags[tag]['problems_answered']:
                                    tags[tag]['problems_answered'].append(item_block_location)
                                    tags[tag]['answers'] = tags[tag]['answers'] + items[item_block_location]['answered']
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
                                        if tag not in tags:
                                            tags[tag] = {
                                                'tag': tag,
                                                'problems': [],
                                                'problems_answered': [],
                                                'answers': 0
                                            }
                                        tags[tag]['problems'].append({
                                            'problem_id': item_block_location,
                                            'criterion': criterions[criterion]['label'],
                                            'possible': criterions[criterion]['possible'],
                                            'earned': criterions[criterion]['earned'],
                                            'answered': items[item_block_location]['answered']
                                        })
                                        if items[item_block_location]['answered'] \
                                                and item_block_location not in tags[tag]['problems_answered']:
                                            tags[tag]['problems_answered'].append(item_block_location)
                                            tags[tag]['answers'] = tags[tag]['answers'] \
                                                                   + items[item_block_location]['answered']

    for tag_k, tag_v in tags.items():
        num_questions = len(tag_v['problems'])
        percent_correct = int((sum([x['earned'] / x['possible'] for x in tag_v['problems']]) / num_questions) * 100)
        tags[tag_k]['num_questions'] = num_questions
        tags[tag_k]['percent_correct'] = percent_correct
    tags_result = sorted(tags.values(), key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
    return tags_result


def progress_main_page(request, course, student):
    tags = tags_student_progress(course, student)
    context = {
        'top5tags': tags[-5:],
        'lowest5tags': tags[:5]
    }
    return context
