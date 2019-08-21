import datetime
import json

from django.conf import settings
from pylti1p3.grade import Grade
from pylti1p3.exception import LtiException
from lms import CELERY_APP
from lti_provider.tasks import ScoresHandler, LTI_TASKS_MAX_RETRIES, get_countdown
from lti_provider.outcomes import OutcomeServiceSendScoreError
from .models import GradedAssignment
from .message_launch import ExtendedDjangoMessageLaunch
from .tool_conf import ToolConfDb


@CELERY_APP.task(name='lti1p3_tool.tasks.send_composite_outcome', max_retries=LTI_TASKS_MAX_RETRIES, bind=True)
def lti1p3_send_composite_outcome(self, user_id, course_id, assignment_id, version):
    handler = Lti1p3ScoresHandler()
    try:
        handler.send_composite_outcome(user_id, course_id, assignment_id, version, self.request.retries)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=get_countdown(self.request.retries))


@CELERY_APP.task(max_retries=LTI_TASKS_MAX_RETRIES, bind=True)
def lti1p3_send_leaf_outcome(self, assignment_id, points_earned, points_possible):
    handler = Lti1p3ScoresHandler()
    try:
        handler.send_leaf_outcome(assignment_id, points_earned, points_possible, self.request.retries)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=get_countdown(self.request.retries))


class Lti1p3ScoresHandler(ScoresHandler):

    _lti_version = '1.3'

    def _get_assignments_for_problem(self, descriptor, user_id, course_key):
        locations = []
        current_descriptor = descriptor
        while current_descriptor:
            locations.append(current_descriptor.location)
            current_descriptor = current_descriptor.get_parent()
        assignments = GradedAssignment.objects.filter(
            user=user_id, course_key=course_key, usage_key__in=locations
        )
        return assignments

    def _send_leaf_outcome(self, assignment_id, points_earned, points_possible):
        lti1p3_send_leaf_outcome.delay(
            assignment_id, points_earned, points_possible
        )

    def _send_composite_outcome(self, user_id, course_id, assignment_id, assignment_version_number):
        lti1p3_send_composite_outcome.apply_async(
            (user_id, course_id, assignment_id, assignment_version_number),
            countdown=settings.LTI_AGGREGATE_SCORE_PASSBACK_DELAY
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
        message_launch = ExtendedDjangoMessageLaunch(None, tool_conf)
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
