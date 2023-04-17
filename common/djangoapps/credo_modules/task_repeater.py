import uuid
import json
import datetime
from django.utils import timezone
from .models import DelayedTask, DelayedTaskStatus, DelayedTaskResult


def get_countdown(attempt_num):
    return (int(2.71 ** attempt_num) + 5) * 60


class TaskRepeater:
    task_id = None
    delayed_task = None

    def __init__(self, task_id=None):
        self.task_id = task_id
        if self.task_id:
            self.delayed_task = DelayedTask.objects.filter(task_id=self.task_id).first()

    def get_current_attempt_num(self):
        if self.delayed_task:
            return self.delayed_task.attempt_num
        else:
            return 0

    def restart(self, celery_task_id, task_name, task_params_lst, err_msg='', max_attempts=10,
                course_id=None, user_id=None, assignment_id=None):

        new_attempt_num = self.get_current_attempt_num() + 1
        if self.delayed_task:
            self.delayed_task.status = DelayedTaskStatus.PROCESSED
            self.delayed_task.result = DelayedTaskResult.FAILURE
            self.delayed_task.save()

        if new_attempt_num > max_attempts:
            return

        countdown = get_countdown(new_attempt_num)
        dt_now = timezone.now()
        start_time = dt_now + datetime.timedelta(seconds=countdown)

        d_task = DelayedTask(
            task_id=str(uuid.uuid4()),
            celery_task_id=celery_task_id,
            task_name=task_name,
            task_params=json.dumps(task_params_lst),
            start_time=start_time,
            countdown=countdown,
            attempt_num=new_attempt_num,
            status=DelayedTaskStatus.CREATED,
            result=DelayedTaskResult.UNKNOWN,
            prev_attempt_err_msg=str(err_msg),
            course_id=course_id,
            user_id=user_id,
            assignment_id=assignment_id
        )
        d_task.save()

    def finish(self):
        if self.delayed_task:
            self.delayed_task.status = DelayedTaskStatus.PROCESSED
            self.delayed_task.result = DelayedTaskResult.SUCCESS
            self.delayed_task.save()
