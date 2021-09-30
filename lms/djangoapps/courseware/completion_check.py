from django.contrib.auth import get_user_model
from lms.djangoapps.courseware.module_render import get_module_by_usage_id
from lms.djangoapps.courseware.utils import get_block_children
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import UsageKey
from completion.models import BlockCompletion


User = get_user_model()


def check_sequential_block_is_completed(course_key, usage_id, user_id):
    from django.test.client import RequestFactory

    user = User.objects.get(id=user_id)
    rf = RequestFactory()
    req = rf.get('/fake-request/')
    req.user = user

    course = modulestore().get_course(course_key)
    block, tracking_context = get_module_by_usage_id(req, str(course_key), usage_id, course=course)
    block_children = get_block_children(block, '', add_correctness=False)

    blocks_ids = [UsageKey.from_string(k) for k in block_children.keys()]
    completion_items = BlockCompletion.objects.filter(context_key=course_key, block_key__in=blocks_ids, user=user)
    blocks = {str(b.block_key): b.completion for b in completion_items}

    is_completed = True
    for block_id, block_data in block_children.items():
        if not block_data.get('has_children') and blocks.get(block_id, 0) != 1:
            is_completed = False
            break
    return is_completed
