import uuid
import tempfile
import os

from django.core.cache import caches
from django.contrib.auth.models import User
from django.db import transaction
from lms import CELERY_APP
from opaque_keys.edx.keys import UsageKey
from xmodule.modulestore.django import modulestore
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from openassessment.fileupload.backends.s3 import Backend as S3Backend
from .models import TurnitinApiKey, TurnitinSubmission, TurnitinUser, TurnitinReportStatus
from .api import TurnitinApi
from .utils import log_action


TURNITIN_TASKS_MAX_RETRIES = 7


def get_countdown(attempt_num):
    return (int(2.71 ** attempt_num) + 5) * 60


@CELERY_APP.task(name='turnitin_integration.tasks.turnitin_create_submissions',
                 max_retries=TURNITIN_TASKS_MAX_RETRIES, bind=True)
def turnitin_create_submissions(self, key_id, submission_uuid, course_id, block_id, user_id):
    try:
        _create_submissions(key_id, submission_uuid, course_id, block_id, user_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=get_countdown(self.request.retries))


@CELERY_APP.task(name='turnitin_integration.tasks.turnitin_generate_report',
                 max_retries=TURNITIN_TASKS_MAX_RETRIES, bind=True)
def turnitin_generate_report(self, turnitin_submission_id):
    try:
        _generate_report(turnitin_submission_id)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=get_countdown(self.request.retries))


def _create_submissions(key_id, submission_uuid, course_id, item_id, user_id):
    usage_key = UsageKey.from_string(item_id)
    block = modulestore().get_item(usage_key)
    user = User.objects.get(id=int(user_id))
    api_key = None

    try:
        api_key = TurnitinApiKey.objects.get(id=int(key_id))
        if not api_key.is_active:
            api_key = None
    except TurnitinApiKey.DoesNotExist:
        pass

    if not api_key:
        log_action('turnitin_task', 'Turnitin API key not found or not active', key_id=key_id,
                   ora_submission_uuid=submission_uuid, item_id=item_id, user_id=user.id)
        return

    b2s = BlockToSequential.objects.filter(course_id=str(course_id), block_id=str(item_id)).first()
    if b2s:
        block_display_name = b2s.sequential_name + ': ' + block.display_name
    else:
        block_display_name = block.display_name

    try:
        turnitin_user = TurnitinUser.objects.get(user=user)
    except TurnitinUser.DoesNotExist:
        turnitin_user = TurnitinUser(
            user=user,
            user_id_hash=str(uuid.uuid4())
        )
        turnitin_user.save()

    s3_backend = S3Backend()
    turnitin_api = TurnitinApi(api_key)

    submissions = TurnitinSubmission.objects.filter(block_id=item_id, ora_submission_id=submission_uuid, user=user,
                                                    turnitin_submission_id='-')

    log_action('turnitin_task', 'Submissions to process: ' + ','.join([str(s.id) for s in submissions]),
               ora_submission_uuid=submission_uuid, item_id=item_id, user_id=user.id)

    cache = caches['default']
    cache_key = 'eula_version_' + str(user.id)
    eula_version = cache.get(cache_key)
    if not eula_version:
        eula_version, eula_url = turnitin_api.get_eula_version()

    submissions_to_remove = []
    for sub in submissions:
        with transaction.atomic():
            is_text_response = False if sub.file_name else True
            filename = sub.file_name if sub.file_name else 'text_response.txt'
            title = block_display_name + ' [' + filename + ']'
            data = sub.get_data()
            if not is_text_response:
                s3_key_exists = s3_backend.check_key_exists(data['file_key'])
                if not s3_key_exists:
                    submissions_to_remove.append(sub.id)
                    continue

            status_code1, resp1 = turnitin_api.create_submission(turnitin_user, title, eula_version)
            success = True if resp1 else False
            turnitin_submission_id = resp1['id'] if resp1 else None

            log_action('turnitin_task', 'API create_submission response for file: ' + filename,
                       ora_submission_uuid=submission_uuid, item_id=item_id, user_id=user.id,
                       turnitin_submission_id=turnitin_submission_id, success=success, status_code=status_code1)

            if not resp1:
                raise Exception("Can't create submission using Turnitin API: status_code=" + str(status_code1))

            if is_text_response:
                content = data['text_response']
                status_code2, resp2 = turnitin_api.upload_file(resp1['id'], filename, content.encode('utf-8'))
            else:
                s3_key = data['file_key']

                tf = tempfile.NamedTemporaryFile(delete=False)
                try:
                    s3_backend.save_key_content_into_file(s3_key, tf)
                    tf.close()

                    tf = open(tf.name, 'rb')
                    content = tf.read()
                    status_code2, resp2 = turnitin_api.upload_file(resp1['id'], filename, content)
                finally:
                    tf.close()
                    os.remove(tf.name)

            log_action('turnitin_task', 'API upload_file response for file: ' + filename,
                       ora_submission_uuid=submission_uuid, item_id=item_id, user_id=user.id,
                       turnitin_submission_id=turnitin_submission_id, status_code=status_code2)
            if not resp2:
                raise Exception("Can't upload file " + filename + " using Turnitin API:"
                                                                  " status_code=" + str(status_code2))

            sub.turnitin_submission_id = resp1['id']
            sub.status = resp1['status']
            sub.save()

    if submissions_to_remove:
        TurnitinSubmission.objects.filter(id__in=submissions_to_remove).delete()


def _generate_report(turnitin_submission_id):
    with transaction.atomic():
        try:
            turnitin_submission = TurnitinSubmission.objects.get(turnitin_submission_id=turnitin_submission_id)
        except TurnitinSubmission.DoesNotExist:
            log_action('turnitin_task', 'Generate report error. Submission not found',
                       turnitin_submission_id=turnitin_submission_id)
            return

        usage_key = UsageKey.from_string(turnitin_submission.block_id)
        block = modulestore().get_item(usage_key)
        add_to_index = block.turnitin_config.get('add_to_index', False)
        auto_exclude_self_matching_scope = block.turnitin_config.get('auto_exclude_self_matching_scope', False)

        api_key = turnitin_submission.api_key
        if not api_key.is_active:
            log_action('turnitin_task', 'Generate report error. API key is inactive', key_id=api_key.id,
                       turnitin_submission_id=turnitin_submission_id)
            return

        turnitin_api = TurnitinApi(api_key)

        status_code, result = turnitin_api.create_report(turnitin_submission_id, add_to_index,
                                                         auto_exclude_self_matching_scope)
        log_action('turnitin_task', 'API create_report response for turnitin_submission_id: ' + turnitin_submission_id,
                   status_code=status_code)
        if result:
            TurnitinSubmission.objects.filter(id=turnitin_submission.id, report_status=TurnitinReportStatus.NOT_SET)\
                    .update(report_status=TurnitinReportStatus.IN_PROGRESS)
