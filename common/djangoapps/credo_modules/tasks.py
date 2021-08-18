import json
import datetime
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from .models import DelayedTask, DelayedTaskStatus
from lms.djangoapps.lti_provider.tasks import send_composite_outcome, send_leaf_outcome
from lms.djangoapps.lti1p3_tool.tasks import lti1p3_send_composite_outcome, lti1p3_send_leaf_outcome
from lms import CELERY_APP
from common.djangoapps.turnitin_integration.tasks import turnitin_create_submissions, turnitin_generate_report


def handle_delayed_tasks():
    dt_2 = timezone.now()
    dt_1 = dt_2 - datetime.timedelta(minutes=15)
    tasks = DelayedTask.objects.filter(
        start_time__gte=dt_1, start_time__lte=dt_2,
        status=DelayedTaskStatus.CREATED).order_by('start_time')
    for t in tasks:
        with transaction.atomic():
            data = json.loads(t.task_params)
            t.status = DelayedTaskStatus.IN_PROGRESS
            t.save()

            if t.task_name == 'send_composite_outcome':
                transaction.on_commit(lambda: send_composite_outcome.apply_async(
                    (data['user_id'], data['course_id'], data['assignment_id'],
                     data['version'], t.task_id),
                    routing_key=settings.HIGH_PRIORITY_QUEUE
                ))
            elif t.task_name == 'send_leaf_outcome':
                transaction.on_commit(lambda: send_leaf_outcome.apply_async(
                    (data['assignment_id'], data['points_earned'], data['points_possible'],
                     t.task_id),
                    routing_key=settings.HIGH_PRIORITY_QUEUE
                ))
            elif t.task_name == 'lti1p3_send_composite_outcome':
                transaction.on_commit(lambda: lti1p3_send_composite_outcome.apply_async(
                    (data['user_id'], data['course_id'], data['assignment_id'],
                     data['version'], t.task_id),
                    routing_key=settings.HIGH_PRIORITY_QUEUE
                ))
            elif t.task_name == 'lti1p3_send_leaf_outcome':
                transaction.on_commit(lambda: lti1p3_send_leaf_outcome.apply_async(
                    (data['assignment_id'], data['points_earned'], data['points_possible'],
                     t.task_id),
                    routing_key=settings.HIGH_PRIORITY_QUEUE
                ))
            elif t.task_name == 'turnitin_create_submissions':
                transaction.on_commit(lambda: turnitin_create_submissions.delay(
                    data['key_id'], data['submission_uuid'], data['course_id'],
                    data['block_id'], data['user_id'], t.task_id
                ))
            elif t.task_name == 'turnitin_generate_report':
                transaction.on_commit(lambda: turnitin_generate_report.delay(data['turnitin_submission_id']))


@CELERY_APP.task(name='common.djangoapps.credo_modules.tasks.exec_delayed_tasks', bind=True)
def exec_delayed_tasks(self):
    handle_delayed_tasks()
