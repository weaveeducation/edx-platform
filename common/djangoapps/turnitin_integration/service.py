import json

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from credo_modules.models import Organization
from student.models import AnonymousUserId
from opaque_keys.edx.keys import CourseKey
from .models import TurnitinApiKey, TurnitinSubmission, TurnitinSubmissionStatus, TurnitinReportStatus
from .api import TurnitinApi
from .tasks import turnitin_create_submissions
from .utils import log_action


TURNITIN_ERROR_MSG_DICT = {
    'UNSUPPORTED_FILETYPE': 'The uploaded filetype is not supported',
    'PROCESSING_ERROR': 'An unspecified error occurred while processing the submissions',
    'TOO_LITTLE_TEXT': 'The submission does not have enough text to generate a Similarity Report '
                       '(a submission must contain at least 20 words)',
    'TOO_MUCH_TEXT': 'The submission has too much text to generate a Similarity Report '
                     '(after extracted text is converted to UTF-8, the submission must contain less than 2MB of text)',
    'CANNOT_EXTRACT_TEXT': 'The submission does not contain any text',
    'TOO_MANY_PAGES': 'The submission has too many pages to generate a Similarity Report '
                      '(a submission cannot contain more than 800 pages)',
    'FILE_LOCKED': 'The uploaded file requires a password in order to be opened',
    'CORRUPT_FILE': 'The uploaded file appears to be corrupt'
}


def get_turnitin_key(org):
    try:
        org_obj = Organization.objects.get(org=org)
        try:
            turnitin_api_key = TurnitinApiKey.objects.get(org=org_obj)
            if turnitin_api_key.is_active:
                return turnitin_api_key
        except TurnitinApiKey.DoesNotExist:
            pass
    except Organization.DoesNotExist:
        pass
    return None


def create_submissions(submission_uuid, student_item_dict, text_response_lst, file_names=None):
    course_id = student_item_dict.get('course_id')
    anonymous_user_id = student_item_dict.get('student_id')
    item_id = student_item_dict.get('item_id')

    backend_setting = getattr(settings, "ORA2_FILEUPLOAD_BACKEND", "s3")
    if backend_setting != "s3":
        return

    if not course_id or not item_id or not anonymous_user_id:
        return

    course_key = CourseKey.from_string(course_id)
    anon_user = AnonymousUserId.objects.get(anonymous_user_id=anonymous_user_id, course_id=course_key)
    user = anon_user.user

    turnitin_key = get_turnitin_key(course_key.org)
    if not turnitin_key:
        log_action('create_submission', 'Turnitin API key not found or not active', ora_submission_uuid=submission_uuid,
                   item_id=item_id, user_id=user.id)
        return

    api = TurnitinApi(turnitin_key)

    if text_response_lst:
        text_response = "\n".join(text_response_lst)
        text_response = text_response.strip()

        if text_response:
            t_sub = TurnitinSubmission(
                api_key=turnitin_key,
                block_id=item_id,
                file_name=None,
                ora_submission_id=submission_uuid,
                turnitin_submission_id='-',
                user=user,
                status='-',
            )
            t_sub.set_data({
                'text_response': text_response,
            })
            t_sub.save()

    if file_names:
        file_names = json.loads(file_names)
        for idx, file_name in enumerate(file_names):
            file_name_lst = file_name.split('.')
            if file_name_lst:
                ext = file_name_lst[-1]
                if api.is_ext_supported(ext):
                    t_sub = TurnitinSubmission(
                        api_key=turnitin_key,
                        block_id=item_id,
                        file_name=file_name,
                        ora_submission_id=submission_uuid,
                        turnitin_submission_id='-',
                        user=user,
                        status='-',
                    )
                    t_sub.set_data({
                        'file_num': idx,
                    })
                    t_sub.save()

    transaction.on_commit(lambda: turnitin_create_submissions.delay(turnitin_key.id, submission_uuid,
                                                                    course_id, item_id, user.id))


def get_submissions_status(ora_submission_id, display_score=True):
    result_list = []
    css_class = 'is--complete'
    statuses = []

    css_status_dict = {
        TurnitinSubmissionStatus.CREATED: 'incomplete',
        TurnitinSubmissionStatus.PROCESSING: 'incomplete',
        TurnitinSubmissionStatus.COMPLETE: 'complete',
        TurnitinSubmissionStatus.ERROR: 'warning'
    }

    title_status_dict = {
        '-': '-',
        TurnitinSubmissionStatus.CREATED: 'Processing',
        TurnitinSubmissionStatus.PROCESSING: 'Processing',
        TurnitinSubmissionStatus.COMPLETE: 'Complete',
        TurnitinSubmissionStatus.ERROR: 'Error'
    }

    submissions = TurnitinSubmission.objects.filter(ora_submission_id=ora_submission_id).order_by('file_name')
    if len(submissions) > 0:
        for s in submissions:
            submission_is_error = s.status == TurnitinSubmissionStatus.ERROR
            submission_is_complete = s.status == TurnitinSubmissionStatus.COMPLETE
            report_is_ready = s.report_status == TurnitinReportStatus.COMPLETE
            data = s.get_data()

            hint = ''
            if submission_is_error:
                hint = str(TURNITIN_ERROR_MSG_DICT.get(data.get('submission', {}).get('error_code', '')))
            elif submission_is_complete and display_score:
                overall_match_percentage = str(data.get('report', {}).get('overall_match_percentage', ''))
                if overall_match_percentage != '':
                    hint = 'Overall Similarity: ' + str(overall_match_percentage) + '%'
                else:
                    hint = 'Overall Similarity: processing'

            result_list.append({
                'id': s.id,
                'title': s.file_name if s.file_name else 'Text response',
                'ora_submission_id': ora_submission_id,
                'status': title_status_dict[s.status] + (('. ' + hint) if hint else ''),
                'submission_is_complete': submission_is_complete,
                'report_is_ready': report_is_ready,
                'css_class': css_status_dict[s.status] if s.status != '-' else 'incomplete',
                'url': reverse('turnitin_report', kwargs={'ora_submission_id': ora_submission_id,
                                                          'submission_id': s.id}) if report_is_ready else None
            })
            statuses.append(s.status)
        if 'CREATED' in statuses or 'PROCESSING' in statuses or '-' in statuses:
            css_class = 'is--in-progress'
    else:
        css_class = ''

    return {
        'result': result_list,
        'css_class': css_class
    }
