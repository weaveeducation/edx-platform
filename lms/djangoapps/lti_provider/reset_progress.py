import hashlib

from django.db import transaction
from django.db.utils import IntegrityError

from lms.djangoapps.instructor_task.tasks_helper.module_state import reset_user_progress
from lms.djangoapps.lti_provider.models import GradedAssignment, LtiContextId, LTI1p1
from xmodule.modulestore.django import modulestore


def check_and_reset_lti_user_progress(context_id, context_data, user, course_key, usage_key,
                                      lis_result_sourcedid=None, lti_version=None):
    if not lti_version:
        lti_version = LTI1p1
    if context_id:
        try:
            context = LtiContextId.objects.get(
                course_key=course_key,
                usage_key=usage_key,
                user=user,
                lti_version=lti_version
            )
            current_properties = context.get_properties()
            if context.value != context_id:
                context.value = context_id
                context.set_properties(context_data)
                context.save()
                with modulestore().bulk_operations(course_key):
                    block = modulestore().get_item(usage_key)
                    reset_user_progress(user, course_key, block, initiator='lti_new_context_id')
                    if lti_version == LTI1p1 and lis_result_sourcedid:
                        lis_result_sourcedid_hash = hashlib.md5(str(lis_result_sourcedid).encode('utf-8')).hexdigest()
                        GradedAssignment.objects.filter(
                            course_key=course_key, usage_key=usage_key, user=user
                        ).exclude(lis_result_sourcedid=lis_result_sourcedid_hash).delete()
            elif current_properties != context_data:
                context.set_properties(context_data)
                context.save()
        except LtiContextId.DoesNotExist:
            try:
                with transaction.atomic():
                    context = LtiContextId(
                        user=user,
                        course_key=course_key,
                        usage_key=usage_key,
                        value=context_id,
                        lti_version=lti_version
                    )
                    context.set_properties(context_data)
                    context.save()
            except IntegrityError:
                pass
