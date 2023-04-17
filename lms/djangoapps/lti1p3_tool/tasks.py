import datetime
import logging
import json

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db import transaction
from lms import CELERY_APP
from lms.djangoapps.lti_provider.models import LtiContextId
from lms.djangoapps.lti_provider.tasks import ScoresHandler, LTI_TASKS_MAX_RETRIES
from lms.djangoapps.lti_provider.outcomes import OutcomeServiceSendScoreError
from lms.djangoapps.lti_provider.views import enroll_user_to_course
from lms.djangoapps.lti1p3_tool.models import LtiUser
from common.djangoapps.student.role_helpers import has_staff_roles
from common.djangoapps.student.models import CourseEnrollment
from common.djangoapps.credo_modules.task_repeater import TaskRepeater
from common.djangoapps.credo_modules.models import check_and_save_enrollment_attributes
from opaque_keys.edx.keys import CourseKey
from .models import GradedAssignment, LtiUserEnrollment, LtiExternalCourse
from .tool_conf import ToolConfDb
from .users import Lti1p3UserService

try:
    from pylti1p3.contrib.django import DjangoMessageLaunch
    from pylti1p3.grade import Grade
    from pylti1p3.exception import LtiException
except ImportError:
    pass


User = get_user_model()
log = logging.getLogger("lti1p3_tool.tasks")


@CELERY_APP.task(name='lms.djangoapps.lti1p3_tool.tasks.lti1p3_send_composite_outcome', bind=True)
def lti1p3_send_composite_outcome(self, user_id, course_id, assignment_id, version, task_id=None):
    handler = Lti1p3ScoresHandler()
    tr = TaskRepeater(task_id)
    try:
        attempt_num = tr.get_current_attempt_num()
        handler.send_composite_outcome(user_id, course_id, assignment_id, version, attempt_num)
        tr.finish()
    except Exception as exc:
        tr.restart(self.request.id, 'lti1p3_send_composite_outcome',
                   [user_id, course_id, assignment_id, version],
                   course_id=course_id, user_id=user_id, assignment_id=assignment_id,
                   err_msg=str(exc), max_attempts=LTI_TASKS_MAX_RETRIES)


@CELERY_APP.task(bind=True)
def lti1p3_send_leaf_outcome(self, assignment_id, points_earned, points_possible, task_id=None):
    handler = Lti1p3ScoresHandler()
    tr = TaskRepeater(task_id)
    try:
        attempt_num = tr.get_current_attempt_num()
        handler.send_leaf_outcome(assignment_id, points_earned, points_possible, attempt_num)
        tr.finish()
    except Exception as exc:
        tr.restart(self.request.id, 'lti1p3_send_leaf_outcome',
                   [assignment_id, points_earned, points_possible],
                   assignment_id=assignment_id, err_msg=str(exc), max_attempts=LTI_TASKS_MAX_RETRIES)


class Lti1p3ScoresHandler(ScoresHandler):

    _lti_version = '1.3'

    def _get_assignments_for_problem(self, descriptor, user_id, course_key):
        locations = []
        current_descriptor = descriptor
        while current_descriptor:
            if current_descriptor.graded:
                locations.append(current_descriptor.location)
            if current_descriptor.category == 'sequential':
                break
            current_descriptor = current_descriptor.get_parent()
        if not locations:
            return []
        assignments = GradedAssignment.objects.filter(
            user=user_id, course_key=course_key, usage_key__in=locations, disabled=False
        )
        return assignments

    def _send_leaf_outcome(self, assignment_id, points_earned, points_possible):
        lti1p3_send_leaf_outcome.apply_async(
            (assignment_id, points_earned, points_possible),
            routing_key=settings.HIGH_PRIORITY_QUEUE
        )

    def _send_composite_outcome(self, user_id, course_id, assignment_id, assignment_version_number):
        lti1p3_send_composite_outcome.apply_async(
            (user_id, course_id, assignment_id, assignment_version_number),
            countdown=settings.LTI_AGGREGATE_SCORE_PASSBACK_DELAY,
            routing_key=settings.HIGH_PRIORITY_QUEUE
        )

    def _get_graded_assignment_by_id(self, assignment_id):
        return GradedAssignment.objects.get(id=assignment_id)

    def send_score_update(self, assignment, weighted_score, request_retries, countdown):
        launch_data = {
            'iss': assignment.lti_tool.issuer,
            'aud': assignment.lti_tool.client_id,
            'https://purl.imsglobal.org/spec/lti-ags/claim/endpoint': assignment.lti_jwt_endpoint
        }
        tool_conf = ToolConfDb()
        message_launch = DjangoMessageLaunch(None, tool_conf)
        message_launch.set_auto_validation(enable=False) \
            .set_jwt({'body': launch_data}) \
            .set_restored() \
            .validate_registration()

        ags = message_launch.get_ags()

        try:
            line_item = ags.find_lineitem_by_id(assignment.lti_lineitem)
            if not line_item:
                raise OutcomeServiceSendScoreError("Lineitem not found in the external LMS: " + assignment.lti_lineitem)

            timestamp = datetime.datetime.utcnow().isoformat(sep='T', timespec='milliseconds') + "Z"

            # activity_progress / grading_progress
            # https://www.imsglobal.org/spec/lti-ags/v2p0#activityprogress
            # https://www.imsglobal.org/spec/lti-ags/v2p0#gradingprogress

            gr = Grade()
            gr.set_score_given(weighted_score)\
                .set_score_maximum(1)\
                .set_timestamp(timestamp)\
                .set_activity_progress('Submitted')\
                .set_grading_progress('FullyGraded')\
                .set_user_id(assignment.lti_jwt_sub)

            result = ags.put_grade(gr, line_item)
            return {
                'request_body': str(gr.get_value()),
                'response_body': json.dumps(result),
                'lis_outcome_service_url': str(line_item.get_value())
            }
        except LtiException as e:
            raise OutcomeServiceSendScoreError(str(e), lis_outcome_service_url=assignment.lti_lineitem)


@CELERY_APP.task(bind=True)
def lti1p3_sync_course_enrollments(self, ext_course_id):
    ext_course = LtiExternalCourse.objects.filter(pk=ext_course_id).first()
    if not ext_course or not ext_course.context_memberships_url:
        return

    edx_course_id = ext_course.edx_course_id
    external_course_id = ext_course.external_course_id
    course_key = CourseKey.from_string(edx_course_id)

    ext_course.users_last_sync_date = timezone.now()
    ext_course.save(update_fields=["users_last_sync_date"])

    lti_tool = ext_course.lti_tool

    launch_data = {
        'iss': lti_tool.issuer,
        'aud': lti_tool.client_id,
        'https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice': {
            'context_memberships_url': ext_course.context_memberships_url,
            "service_versions": [
                "2.0"
            ],
        }
    }
    tool_conf = ToolConfDb()
    message_launch = DjangoMessageLaunch(None, tool_conf)
    message_launch.set_auto_validation(enable=False) \
        .set_jwt({'body': launch_data}) \
        .set_restored() \
        .validate_registration()

    nrps = message_launch.get_nrps()
    context = nrps.get_context()
    context_label = context.get('label')
    if context_label:
        context_label = context_label.strip()
    context_title = context.get('title')
    if context_title:
        context_title = context_title.strip()

    members = nrps.get_members()
    us = Lti1p3UserService()
    processed_users = []
    processed_edx_users = []
    external_users_dict = {}

    existing_enrollments = LtiUserEnrollment.objects.filter(external_course=ext_course).select_related('lti_user')
    existing_enrollments_dict = {}
    for enr in existing_enrollments:
        existing_enrollments_dict[enr.lti_user.lti_jwt_sub] = enr.lti_user

    # check members to automatically enroll them
    for member in members:
        log.info("Process LTI member %s", member)

        lti_status = member.get('status')
        if lti_status:
            lti_status = lti_status.strip().lower()
        if lti_status != 'active':
            continue

        with transaction.atomic():
            lti_user_id = member.get('user_id')
            lti_user = us.get_lti_user(lti_user_id, lti_tool, member)
            us.update_external_enrollment(lti_user, ext_course, context_label=context_label, context_title=context_title)

            user = lti_user.edx_user
            processed_users.append(lti_user_id)
            processed_edx_users.append(lti_user.edx_user_id)
            external_users_dict[user.id] = lti_user_id

            roles = []
            lti_roles = member.get('roles', [])
            for role in lti_roles:
                roles_lst = role.split('#')
                if len(roles_lst) > 1:
                    roles.append(roles_lst[1])

            enroll_result = enroll_user_to_course(user, course_key, roles)
            if enroll_result:
                log.info("New user %s was enrolled to course %s", user.id, edx_course_id)

                enrollment_attributes = {}
                if context_label:
                    enrollment_attributes['context_label'] = context_label
                check_and_save_enrollment_attributes(enrollment_attributes, user, course_key)

    # check members to automatically unenroll them
    if lti_tool.automatically_unenroll_users:

        # remove LtiUserEnrollment objects for absent users
        for edx_user_id, lti_user in existing_enrollments_dict.items():
            if edx_user_id not in processed_users:
                LtiUserEnrollment.objects.filter(lti_user=lti_user, external_course=ext_course).delete()

        edx_enrollments = CourseEnrollment.objects.users_enrolled_in(course_key)
        for user in edx_enrollments:
            if user.id in processed_edx_users or user.is_staff or user.is_superuser or has_staff_roles(user, course_key):
                continue

            lti_users = LtiUser.objects.filter(
                edx_user=user,
                lti_tool=lti_tool
            )

            # skip non-LTI users
            if len(lti_users) == 0:
                continue

            # try to find other enrollments in the same edx course
            other_enrollments_exists = LtiUserEnrollment.objects.filter(
                lti_user__edx_user=user,
                external_course__edx_course_id=edx_course_id
            ).exclude(external_course__external_course_id=external_course_id).exists()

            # and skip such users
            if other_enrollments_exists:
                continue

            contexts = LtiContextId.objects.filter(user=user, course_key=course_key)
            contexts_list_uniq = []
            for context in contexts:
                if context.value.strip() not in contexts_list_uniq:
                    contexts_list_uniq.append(context.value.strip())

            if len(contexts_list_uniq) > 1\
              or (len(contexts_list_uniq) == 1 and contexts_list_uniq[0] != external_course_id):
                continue

            log.info("Try to unenroll user: %s", user.id)

            with transaction.atomic():
                # remove LTI enrollment objects
                lti_user_ids = [l.id for l in lti_users if l.lti_jwt_sub not in processed_users]
                if len(lti_user_ids) > 0:
                    LtiUserEnrollment.objects.filter(
                        lti_user_id__in=lti_user_ids,
                        external_course=ext_course).delete()

                CourseEnrollment.unenroll(user, course_key)
