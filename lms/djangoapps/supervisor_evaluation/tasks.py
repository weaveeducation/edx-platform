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
from common.djangoapps.credo_modules.task_repeater import TaskRepeater
from common.djangoapps.credo_modules.models import SupervisorEvaluationInvitation
from common.djangoapps.student.models import CourseAccessRole
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from opaque_keys.edx.keys import CourseKey
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
def supervisor_survey_check_finish_task(self, invitation_id, sequential_id, skills_mfe_url, email_from_address):
    with transaction.atomic():
        invitation = SupervisorEvaluationInvitation.objects.filter(id=invitation_id).first()
        if invitation and not invitation.survey_finished:
            course_key = CourseKey.from_string(invitation.course_id)
            with modulestore().bulk_operations(course_key):
                res = check_sequential_block_is_completed(course_key, sequential_id, invitation.student_id)
                if res:
                    invitation.survey_finished = True
                    invitation.save()
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
            seq_block = BlockToSequential.objects.filter(sequential_id=survey_sequential_block_id, deleted=False,
                                                         visible_to_staff_only=False).first()
            if seq_block:
                student = User.objects.get(id=invitation.student_id)
                pdf_path = generate_supervisor_pdf(skills_mfe_url, survey_sequential_block_id, student)
                send_supervisor_pdf(pdf_path, email_from_address, seq_block.sequential_name,
                                    invitation.course_id, student)
                os.remove(pdf_path)
        tr.finish()
    except Exception as exc:
        if pdf_path:
            os.remove(pdf_path)
        tr.restart(self.request.id, 'generate_supervisor_pdf_task',
                   [invitation_id, survey_sequential_block_id, skills_mfe_url, email_from_address],
                   err_msg=str(exc), max_attempts=SUPERVISOR_PDF_TASKS_MAX_RETRIES)


def generate_supervisor_pdf(skills_mfe_url, seq_block_id, student):
    jwt_header_and_payload, jwt_signature = get_jwt_credentials(FakeRequest(), student)
    mfe_url = skills_mfe_url + '/supervisor/' + seq_block_id + '/?headless=true'

    cookies = {}
    cookies[jwt_cookie_header_payload_name()] = jwt_header_and_payload
    cookies[jwt_cookie_signature_name()] = jwt_signature
    headers = {'USE-JWT-COOKIE': 'true'}

    r = requests.get(mfe_url, cookies=cookies, headers=headers)
    if r.status_code == 200:
        report_html = r.text
    else:
        raise Exception('MFE invalid status code: ' + str(r.status_code))

    tf = tempfile.NamedTemporaryFile(mode='w+b', delete=False, suffix='.pdf')
    css = CSS(string='@page { size: A4; margin: 0; size: portrait; }')
    pdf_bytes = HTML(string=report_html, base_url=skills_mfe_url).write_pdf(stylesheets=[css])
    tf.write(pdf_bytes)
    tf.close()

    return tf.name


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
