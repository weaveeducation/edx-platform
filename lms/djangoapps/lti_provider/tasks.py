"""
Asynchronous tasks for the LTI provider app.
"""

import logging
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from opaque_keys.edx.keys import CourseKey

import lms.djangoapps.lti_provider.outcomes as outcomes
from lms import CELERY_APP
from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from lms.djangoapps.lti_provider.models import GradedAssignment, SendScoresLock, log_lti
from lms.djangoapps.lti_provider.views import parse_course_and_usage_keys
from common.djangoapps.credo_modules.task_repeater import TaskRepeater, get_countdown
from xmodule.modulestore.django import modulestore

log = logging.getLogger("edx.lti_provider")
User = get_user_model()


LTI_TASKS_MAX_RETRIES = 7


@CELERY_APP.task(name='lms.djangoapps.lti_provider.tasks.send_composite_outcome', bind=True)
def send_composite_outcome(self, user_id, course_id, assignment_id, version, task_id=None):
    """
    Calculate and transmit the score for a composite module (such as a
    vertical).

    A composite module may contain multiple problems, so we need to
    calculate the total points earned and possible for all child problems. This
    requires calculating the scores for the whole course, which is an expensive
    operation.

    Callers should be aware that the score calculation code accesses the latest
    scores from the database. This can lead to a race condition between a view
    that updates a user's score and the calculation of the grade. If the Celery
    task attempts to read the score from the database before the view exits (and
    its transaction is committed), it will see a stale value. Care should be
    taken that this task is not triggered until the view exits.

    The GradedAssignment model has a version_number field that is incremented
    whenever the score is updated. It is used by this method for two purposes.
    First, it allows the task to exit if it detects that it has been superseded
    by another task that will transmit the score for the same assignment.
    Second, it prevents a race condition where two tasks calculate different
    scores for a single assignment, and may potentially update the campus LMS
    in the wrong order.
    """
    handler = ScoresHandler()
    tr = TaskRepeater(task_id)
    try:
        attempt_num = tr.get_current_attempt_num()
        handler.send_composite_outcome(user_id, course_id, assignment_id, version, attempt_num)
        tr.finish()
    except Exception as exc:
        tr.restart(self.request.id, 'send_composite_outcome',
                   {'user_id': user_id, 'course_id': course_id, 'assignment_id': assignment_id, 'version': version},
                   err_msg=str(exc), max_attempts=LTI_TASKS_MAX_RETRIES)


@CELERY_APP.task(bind=True)
def send_leaf_outcome(self, assignment_id, points_earned, points_possible, task_id=None):
    """
    Calculate and transmit the score for a single problem. This method assumes
    that the individual problem was the source of a score update, and so it
    directly takes the points earned and possible values. As such it does not
    have to calculate the scores for the course, making this method far faster
    than send_outcome_for_composite_assignment.
    """
    handler = ScoresHandler()
    tr = TaskRepeater(task_id)
    try:
        attempt_num = tr.get_current_attempt_num()
        handler.send_leaf_outcome(assignment_id, points_earned, points_possible, attempt_num)
        tr.finish()
    except Exception as exc:
        tr.restart(self.request.id, 'send_leaf_outcome',
                   {'assignment_id': assignment_id, 'points_earned': points_earned, 'points_possible': points_possible},
                   err_msg=str(exc), max_attempts=LTI_TASKS_MAX_RETRIES)


class ScoresHandler(object):

    _lti_version = '1.1'

    def score_changed_handler(self, **kwargs):  # pylint: disable=unused-argument
        points_possible = kwargs.get('weighted_possible', None)
        points_earned = kwargs.get('weighted_earned', None)
        user_id = kwargs.get('user_id', None)
        course_id = kwargs.get('course_id', None)
        usage_id = kwargs.get('usage_id', None)

        if None not in (points_earned, points_possible, user_id, course_id):
            course_key, usage_key = parse_course_and_usage_keys(course_id, usage_id)
            assignments = self._increment_assignment_versions(course_key, usage_key, user_id)
            for assignment in assignments:
                if assignment.usage_key == usage_key:
                    self._send_leaf_outcome(assignment.id, points_earned, points_possible)
                    log_lti('send_leaf_outcome_task_added', user_id, '', course_id, False, assignment, None,
                            points_possible=points_possible, points_earned=points_earned, usage_id=usage_id,
                            lti_version=self._lti_version)
                else:
                    self._send_composite_outcome(user_id, course_id, assignment.id, assignment.version_number)
                    log_lti('send_composite_outcome_task_added', user_id, '', course_id, False, assignment, None,
                            points_possible=points_possible, points_earned=points_earned, usage_id=usage_id,
                            countdown=settings.LTI_AGGREGATE_SCORE_PASSBACK_DELAY, lti_version=self._lti_version)
        else:
            error_msg = "Outcome Service: Required signal parameter is None. points_possible: %s," \
                        " points_earned: %s, user_id: %s, course_id: %s, usage_id: %s" % \
                        (points_possible, points_earned, user_id, course_id, usage_id)
            log_lti('score_changed_error', user_id, error_msg, course_id, True, None, None,
                    points_possible=points_possible, points_earned=points_earned, usage_id=usage_id,
                    lti_version=self._lti_version)
            log.error(error_msg)

    def _get_assignments_for_problem(self, descriptor, user_id, course_key):
        return outcomes.get_assignments_for_problem(
            descriptor, user_id, course_key
        )

    def _send_leaf_outcome(self, assignment_id, points_earned, points_possible):
        send_leaf_outcome.apply_async(
            (assignment_id, points_earned, points_possible),
            routing_key=settings.HIGH_PRIORITY_QUEUE
        )

    def _send_composite_outcome(self, user_id, course_id, assignment_id, assignment_version_number):
        send_composite_outcome.apply_async(
            (user_id, course_id, assignment_id, assignment_version_number),
            countdown=settings.LTI_AGGREGATE_SCORE_PASSBACK_DELAY,
            routing_key=settings.HIGH_PRIORITY_QUEUE
        )

    def _increment_assignment_versions(self, course_key, usage_key, user_id):
        """
        Update the version numbers for all assignments that are affected by a score
        change event. Returns a list of all affected assignments.
        """
        problem_descriptor = modulestore().get_item(usage_key)
        # Get all assignments involving the current problem for which the campus LMS
        # is expecting a grade. There may be many possible graded assignments, if
        # a problem has been added several times to a course at different
        # granularities (such as the unit or the vertical).
        assignments = self._get_assignments_for_problem(problem_descriptor, user_id, course_key)
        for assignment in assignments:
            assignment.version_number += 1
            assignment.save()
        return assignments

    def send_composite_outcome(self, user_id, course_id, assignment_id, version, request_retries):
        assignment = self._get_graded_assignment_by_id(assignment_id)
        task_id = str(uuid.uuid4())

        try:
            log_lti('send_composite_outcome_task_started', user_id, '', course_id, False, assignment, None, task_id,
                    version=version, lti_version=self._lti_version)

            if version != assignment.version_number:
                log_lti('send_composite_outcome_task_skipped', user_id, '', course_id, False, assignment, None, task_id,
                        version=version, lti_version=self._lti_version)
                log.info(
                    "Score passback for GradedAssignment %s skipped. More recent score available.",
                    assignment.id
                )
                return
            course_key = CourseKey.from_string(course_id)
            mapped_usage_key = assignment.usage_key.map_into_course(course_key)
            user = User.objects.get(id=user_id)
            course = modulestore().get_course(course_key, depth=0)
            course_grade = CourseGradeFactory().read(user, course)
            earned, possible = course_grade.score_for_module(mapped_usage_key)
            if possible == 0:
                weighted_score = 0
            else:
                weighted_score = float(earned) / float(possible)

            request_body = None
            response_body = None
            lis_outcome_service_url = None

            assignment = self._get_graded_assignment_by_id(assignment_id)
            if assignment.version_number == version:
                log_lti('send_composite_outcome_task_send_score', user_id, '', course_id, False, assignment,
                        weighted_score, task_id, version=version, lti_version=self._lti_version)

                with SendScoresLock(assignment_id):
                    response_data = self.send_score_update(assignment, weighted_score, request_retries,
                                                           get_countdown(request_retries))
                    request_body = response_data['request_body']
                    response_body = response_data['response_body']
                    lis_outcome_service_url = response_data['lis_outcome_service_url']

            log_lti('send_composite_outcome_task_finished', user_id, '', course_id, False, assignment, weighted_score,
                    task_id, response_body, request_body, lis_outcome_service_url, version=version,
                    lti_version=self._lti_version)
        except Exception as exc:
            request_body = getattr(exc, 'request_body', None)
            response_body = getattr(exc, 'response_body', None)
            request_error = getattr(exc, 'request_error', None)
            lis_outcome_service_url = getattr(exc, 'lis_outcome_service_url', None)
            message = getattr(exc, 'message', repr(exc))
            if request_error:
                message = message + ', request error: ' + request_error
            log_lti('send_composite_outcome_task_error', user_id, message, course_id, True,
                    assignment, None, task_id, response_body, request_body, lis_outcome_service_url, version=version,
                    request_error=request_error, lti_version=self._lti_version)
            raise

    def send_leaf_outcome(self, assignment_id, points_earned, points_possible, request_retries):
        assignment = self._get_graded_assignment_by_id(assignment_id)
        task_id = str(uuid.uuid4())

        try:
            log_lti('send_leaf_outcome_task_started', assignment.user.id, '', str(assignment.course_key), False,
                    assignment, None, task_id, points_earned=points_earned, points_possible=points_possible,
                    lti_version=self._lti_version)

            if points_possible == 0:
                weighted_score = 0
            else:
                weighted_score = float(points_earned) / float(points_possible)

            log_lti('send_leaf_outcome_task_send_score', assignment.user.id, '', str(assignment.course_key), False,
                    assignment, weighted_score, task_id, points_earned=points_earned, points_possible=points_possible,
                    lti_version=self._lti_version)

            with SendScoresLock(assignment_id):
                response_data = self.send_score_update(assignment, weighted_score, request_retries,
                                                       get_countdown(request_retries))
                request_body = response_data['request_body']
                response_body = response_data['response_body']
                lis_outcome_service_url = response_data['lis_outcome_service_url']

            log_lti('send_leaf_outcome_task_finished', assignment.user.id, '', str(assignment.course_key), False,
                    assignment, weighted_score, task_id, response_body, request_body, lis_outcome_service_url,
                    points_earned=points_earned, points_possible=points_possible, lti_version=self._lti_version)
        except Exception as exc:
            request_body = getattr(exc, 'request_body', None)
            response_body = getattr(exc, 'response_body', None)
            request_error = getattr(exc, 'request_error', None)
            lis_outcome_service_url = getattr(exc, 'lis_outcome_service_url', None)
            message = getattr(exc, 'message', repr(exc))
            if request_error:
                message = message + ', request error: ' + request_error
            log_lti('send_leaf_outcome_task_error', assignment.user.id, message,
                    str(assignment.course_key), True, assignment, None, task_id, response_body,
                    request_body, lis_outcome_service_url,
                    points_earned=points_earned, points_possible=points_possible, request_error=request_error,
                    lti_version=self._lti_version)
            raise

    def _get_graded_assignment_by_id(self, assignment_id):
        return GradedAssignment.objects.get(id=assignment_id)

    def send_score_update(self, assignment, weighted_score, request_retries, countdown):
        return outcomes.send_score_update(assignment, weighted_score, request_retries, countdown)
