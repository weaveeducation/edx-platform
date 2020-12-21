import json
import logging
from django.contrib.auth.models import User
from django.conf import settings
from lms import CELERY_APP
from lms.djangoapps.courseware.models import StudentModule
from lms.djangoapps.courseware.module_render import get_module_by_usage_id
from lms.djangoapps.courseware.utils import get_block_children, CREDO_GRADED_ITEM_CATEGORIES
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey, UsageKey
from credo_modules.models import get_student_properties_event_data
from completion.models import BlockCompletion
from eventtracking import tracker

log = logging.getLogger("edx.courseware")


@CELERY_APP.task
def track_sequential_viewed_task(course_key_str, usage_key_str, user_id):
    user_id = int(user_id)
    log.info("Task to send sequential_viewed event was started: course_key=%s, usage_key=%s, user_id=%d"
             % (course_key_str, usage_key_str, user_id))

    course_key = CourseKey.from_string(course_key_str)
    usage_key = UsageKey.from_string(usage_key_str)

    user = User.objects.get(id=user_id)

    student_properties_data = get_student_properties_event_data(user, course_key, parent_id=usage_key_str)

    with modulestore().bulk_operations(course_key):
        block = modulestore().get_item(usage_key)
        block_children = get_block_children(block, '', add_correctness=False)

    for problem_loc, problem_details in block_children.items():
        descriptor = problem_details['data']
        category = problem_details['category']

        if category in CREDO_GRADED_ITEM_CATEGORIES:
            item_dict = {
                'student_properties_aside': student_properties_data,
                'sequential_block_id': str(block.location),
                'usage_key': problem_loc,
                'display_name': descriptor.display_name,
                'question_text': problem_details['question_text'],
                'category': category
            }

            tagging_aside_name = 'tagging_aside'
            if category == 'openassessment':
                tagging_aside_name = 'tagging_ora_aside'
                item_dict['rubrics'] = descriptor.rubric_criteria
                item_dict['rubric_count'] = len(descriptor.rubric_criteria)
                item_dict['support_multiple_rubrics'] = descriptor.support_multiple_rubrics
                item_dict['is_additional_rubric'] = descriptor.is_additional_rubric
                item_dict['ungraded'] = descriptor.ungraded

            for aside in descriptor.runtime.get_asides(descriptor):
                if aside.scope_ids.block_type == tagging_aside_name:
                    item_dict[tagging_aside_name] = aside.saved_tags

            context = {
                'user_id': user_id,
                'org_id': course_key.org,
                'course_id': str(course_key)
            }

            with tracker.get_tracker().context('sequential_block.viewed', context):
                tracker.emit('sequential_block.viewed', item_dict)

    log.info("Task to send sequential_viewed event was finished: course_key=%s, usage_key=%s, user_id=%d"
             % (course_key_str, usage_key_str, user_id))


@CELERY_APP.task
def ora_multiple_rubrics_propagate_answer(course_id, usage_id, user_id,
                                          student_item_dict, student_sub_dict, student_files_info):
    course_key = CourseKey.from_string(course_id)
    usage_key = UsageKey.from_string(usage_id)
    student = User.objects.get(id=user_id)
    if not student_files_info:
        student_files_info = {}

    with modulestore().bulk_operations(course_key):
        course = modulestore().get_course(course_key)
        source_block = modulestore().get_item(usage_key)
        if source_block.support_multiple_rubrics and source_block.block_unique_id:
            vertical_block = source_block.get_parent()
            for child in vertical_block.get_children():
                if child.category == 'openassessment' and child.is_additional_rubric\
                  and child.source_block_unique_id == source_block.block_unique_id:
                    try:
                        _copy_ora_submission(course, course_key, child, student, student_item_dict.copy(),
                                         student_sub_dict.copy(), student_files_info)
                    except Exception as e:
                        if settings.DEBUG:
                            print('Error during "ora_multiple_rubrics_propagate_answer" task processing: ', e)
                        raise


def _copy_ora_submission(course, course_key, child_block, student, student_item_dict, student_sub_dict,
                         student_files_info):
    from submissions import api
    from django.test.client import RequestFactory

    rf = RequestFactory()
    req = rf.get('/fake-request/')
    req.user = student

    ora_additional_rubric, tracking_context = get_module_by_usage_id(
        req, str(course_key), str(child_block.location), course=course)

    if ora_additional_rubric.ungraded or not ora_additional_rubric.display_rubric_step_to_students:
        BlockCompletion.objects.submit_completion(
            user=student,
            block_key=ora_additional_rubric.location,
            completion=1.0,
        )

    student_item_dict['item_id'] = str(child_block.location)
    submission = api.create_submission(student_item_dict, student_sub_dict)
    ora_additional_rubric.create_workflow(submission["uuid"])

    query_kwargs = {
        'course_id': course_key,
        'module_state_key': child_block.location,
        'student': student,
        'module_type': 'openassessment'
    }
    try:
        module = StudentModule.objects.get(**query_kwargs)
    except StudentModule.DoesNotExist:
        module = StudentModule(**query_kwargs)
    state = {
        'submission_uuid': submission["uuid"]
    }
    if student_files_info:
        state.update(student_files_info)
    module.state = json.dumps(state)
    module.save()

    with tracker.get_tracker().context('module', tracking_context):
        ora_additional_rubric.generate_create_submission_event(submission)
