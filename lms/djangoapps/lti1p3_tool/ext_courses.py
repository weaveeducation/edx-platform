from django.utils import timezone
from django.db import IntegrityError, transaction
from .models import LtiExternalCourse
from .tasks import lti1p3_sync_course_enrollments


def process_external_course(message_launch, course_id, external_course_id, lti_tool):
    context_memberships_url = None
    if message_launch.has_nrps():
        message_launch_data = message_launch.get_launch_data()
        context_memberships_url = message_launch_data.get('https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice', {}).get('context_memberships_url')

    ext_course = LtiExternalCourse.objects.filter(
        external_course_id=external_course_id, edx_course_id=course_id).first()

    if ext_course and ext_course.lti_tool.id != lti_tool.id:
        ext_course.lti_tool = lti_tool
        ext_course.save(update_fields=["lti_tool"])

    if ext_course and context_memberships_url != ext_course.context_memberships_url:
        ext_course.context_memberships_url = context_memberships_url
        ext_course.save(update_fields=["context_memberships_url"])

    if not ext_course:
        try:
            with transaction.atomic():
                ext_course = LtiExternalCourse(
                    external_course_id=external_course_id,
                    edx_course_id=course_id,
                    lti_tool=lti_tool,
                    context_memberships_url=context_memberships_url,
                )
                ext_course.save()
        except IntegrityError:
            ext_course = LtiExternalCourse.objects.filter(
                external_course_id=external_course_id, edx_course_id=course_id).first()

    if context_memberships_url:
        time_diff = None
        if ext_course.users_last_sync_date:
            time_diff = timezone.now() - ext_course.users_last_sync_date
        if time_diff is None or time_diff.total_seconds() > 600:  # 10 min
            ext_course.users_last_sync_date = timezone.now()
            ext_course.save(update_fields=["users_last_sync_date"])
            if lti_tool.automatically_enroll_users:
                transaction.on_commit(lambda: lti1p3_sync_course_enrollments.delay(ext_course.id))

    return ext_course
