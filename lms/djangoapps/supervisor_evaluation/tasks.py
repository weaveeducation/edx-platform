import logging
import os
import tempfile
import requests

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMessage
from django.db import transaction
from lms import CELERY_APP
from lms.djangoapps.courseware.completion_check import check_sequential_block_is_completed
from lms.djangoapps.supervisor_evaluation.utils import get_course_block_with_survey, copy_progress
from common.djangoapps.credo_modules.task_repeater import TaskRepeater
from common.djangoapps.credo_modules.models import SupervisorEvaluationInvitation
from common.djangoapps.student.models import CourseAccessRole
from opaque_keys.edx.keys import CourseKey, UsageKey
from edx_rest_framework_extensions.auth.jwt.cookies import jwt_cookie_header_payload_name, jwt_cookie_signature_name
from openedx.core.djangoapps.user_authn.cookies import get_jwt_credentials
from xmodule.modulestore.django import modulestore
from weasyprint import HTML, CSS


SUPERVISOR_PDF_TASKS_MAX_RETRIES = 7
User = get_user_model()
log = logging.getLogger("supervisor_evaluation.tasks")


class FakeRequest:
    META = {}


@CELERY_APP.task(name='lms.djangoapps.supervisor_evaluation.tasks.supervisor_survey_check_finish_task', bind=True)
def supervisor_survey_check_finish_task(self, invitation_id, skills_mfe_url, email_from_address,
                                        supervisor_generate_pdf):
    with transaction.atomic():
        invitation = SupervisorEvaluationInvitation.objects.filter(id=invitation_id).first()
        if invitation and not invitation.survey_finished and invitation.supervisor_user_id:
            course_key = CourseKey.from_string(invitation.course_id)
            usage_key = UsageKey.from_string(invitation.evaluation_block_id)

            student = User.objects.filter(id=invitation.student_id).first()
            supervisor = User.objects.filter(id=invitation.supervisor_user_id).first()
            if not student or not supervisor:
                return

            with modulestore().bulk_operations(course_key):
                supervisor_evaluation_xblock = modulestore().get_item(usage_key)
                survey_sequential_block = get_course_block_with_survey(course_key, supervisor_evaluation_xblock)
                sequential_id = str(survey_sequential_block.location)

                res, block_keys = check_sequential_block_is_completed(
                    course_key, sequential_id, invitation.supervisor_user_id)
                if res and block_keys:
                    invitation.survey_finished = True
                    invitation.save()

                    copy_progress(course_key, block_keys, supervisor, student)
                    if supervisor_generate_pdf:
                        transaction.on_commit(lambda: generate_supervisor_pdf_task.delay(
                            invitation.id, sequential_id, skills_mfe_url, email_from_address))


@CELERY_APP.task(name='common.djangoapps.credo_modules.tasks.generate_supervisor_pdf_task', bind=True)
def generate_supervisor_pdf_task(self, invitation_id, survey_sequential_block_id, skills_mfe_url,
                                 email_from_address, task_id=None):
    tr = TaskRepeater(task_id)
    pdf_path = None
    try:
        invitation = SupervisorEvaluationInvitation.objects.filter(id=invitation_id).first()
        if invitation:
            course_key = CourseKey.from_string(invitation.course_id)
            usage_key = UsageKey.from_string(survey_sequential_block_id)
            with modulestore().bulk_operations(course_key):
                survey_sequential_block = modulestore().get_item(usage_key)
                sequential_name = survey_sequential_block.display_name

                student = User.objects.get(id=invitation.student_id)
                tf = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.pdf')
                pdf_bytes = generate_supervisor_pdf(skills_mfe_url, invitation.url_hash, student)
                tf.write(pdf_bytes)
                tf.close()
                pdf_path = tf.name

                send_supervisor_pdf(pdf_path, email_from_address, sequential_name, invitation.course_id, student)
                os.remove(pdf_path)
        tr.finish()
    except Exception as exc:
        if pdf_path:
            os.remove(pdf_path)
        tr.restart(self.request.id, 'generate_supervisor_pdf_task',
                   [invitation_id, survey_sequential_block_id, skills_mfe_url, email_from_address],
                   err_msg=str(exc), max_attempts=SUPERVISOR_PDF_TASKS_MAX_RETRIES)


def generate_supervisor_pdf(skills_mfe_url, hash_id, student):
    jwt_header_and_payload, jwt_signature = get_jwt_credentials(FakeRequest(), student)
    mfe_url = skills_mfe_url + '/supervisor/results/' + hash_id + '/?headless=true'

    cookies = {}
    cookies[jwt_cookie_header_payload_name()] = jwt_header_and_payload
    cookies[jwt_cookie_signature_name()] = jwt_signature
    headers = {'USE-JWT-COOKIE': 'true'}

    r = requests.get(mfe_url, cookies=cookies, headers=headers)
    if r.status_code == 200:
        report_html = r.text
    else:
        raise Exception('MFE invalid status code: ' + str(r.status_code))

    css = CSS(string='@page { size: A4; margin: 0; }')
    pdf_bytes = HTML(string=report_html, base_url=skills_mfe_url).write_pdf(stylesheets=[css])
    return pdf_bytes


def send_supervisor_pdf(pdf_path, email_from_address, seq_block_name, course_id, student):
    course_key = CourseKey.from_string(course_id)
    course_staff_members = CourseAccessRole.objects.filter(role__in=['instructor', 'staff'], course_id=course_key)
    emails = [student.email]
    for r in course_staff_members:
        if r.user.email not in emails:
            emails.append(r.user.email)

    if settings.DEBUG:
        log.info("Supervisor report - recipient list: " + str(emails))

    email = EmailMessage(
        "Supervisor's report: " + seq_block_name, '', email_from_address, emails)
    email.attach_file(pdf_path)
    email.send(fail_silently=False)
