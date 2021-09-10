import datetime
import json

from django.conf import settings
from lms import CELERY_APP
from lms.djangoapps.lti_provider.tasks import ScoresHandler, LTI_TASKS_MAX_RETRIES
from lms.djangoapps.lti_provider.outcomes import OutcomeServiceSendScoreError
from common.djangoapps.credo_modules.task_repeater import TaskRepeater
from .models import GradedAssignment
from .tool_conf import ToolConfDb

try:
    from pylti1p3.contrib.django import DjangoMessageLaunch
    from pylti1p3.grade import Grade
    from pylti1p3.exception import LtiException
except ImportError:
    pass


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

            timestamp = datetime.datetime.utcnow().isoformat()

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
