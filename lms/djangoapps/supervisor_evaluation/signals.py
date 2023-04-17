from urllib.parse import urlparse
from crum import get_current_request
from completion.models import BlockCompletion
from django.db import models, transaction
from django.dispatch import receiver
from django.conf import settings
from lms.djangoapps.supervisor_evaluation.tasks import supervisor_survey_check_finish_task
from common.djangoapps.credo_modules.models import SupervisorEvaluationInvitation
from common.djangoapps.credo_modules.utils import get_skills_mfe_url
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


@receiver(models.signals.post_save, sender=BlockCompletion)
def supervisor_survey_check_finish(**kwargs):
    request = get_current_request()

    skills_mfe_url = get_skills_mfe_url()
    if not skills_mfe_url or settings.DEBUG:
        return

    hash_id = None
    referer_url = request.META.get('HTTP_REFERER', '')
    if referer_url:
        passed_referer_url = urlparse(referer_url)
        if passed_referer_url.path.startswith('/supervisor/evaluation/'):
            hash_id = passed_referer_url.path.split('/')[-1]

    if hash_id:
        email_from_address = configuration_helpers.get_value('email_from_address',
                                                             settings.BULK_EMAIL_DEFAULT_FROM_EMAIL)
        supervisor_generate_pdf = configuration_helpers.get_value('supervisor_generate_pdf', False)

        invitation = SupervisorEvaluationInvitation.objects.filter(
            url_hash=hash_id, survey_finished=False).first()
        if invitation:
            transaction.on_commit(lambda: supervisor_survey_check_finish_task.delay(
                invitation.id, skills_mfe_url, email_from_address, supervisor_generate_pdf
            ))
