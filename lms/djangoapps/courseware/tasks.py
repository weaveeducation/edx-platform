import logging
from lms import CELERY_APP
from django.contrib.auth.models import User
from xmodule.modulestore.django import modulestore
from courseware.utils import get_block_children, CREDO_GRADED_ITEM_CATEGORIES
from opaque_keys.edx.keys import CourseKey, UsageKey
from credo_modules.models import get_student_properties_event_data
from eventtracking import tracker

log = logging.getLogger("edx.courseware")


@CELERY_APP.task
def track_sequential_viewed_task(course_key_str, usage_key_str, user_id):
    user_id = int(user_id)
    log.info(u"Task to send sequential_viewed event was started: course_key=%s, usage_key=%s, user_id=%d"
             % (course_key_str, usage_key_str, user_id))

    course_key = CourseKey.from_string(course_key_str)
    usage_key = UsageKey.from_string(usage_key_str)

    user = User.objects.get(id=user_id)

    student_properties_data = get_student_properties_event_data(user, course_key)

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

    log.info(u"Task to send sequential_viewed event was finished: course_key=%s, usage_key=%s, user_id=%d"
             % (course_key_str, usage_key_str, user_id))
