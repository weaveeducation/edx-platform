import json

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from .api import TurnitinApi
from .models import TurnitinApiKey, TurnitinSubmission, TurnitinReportStatus, TurnitinUser
from .tasks import turnitin_generate_report
from .utils import generate_hmac256_signature, log_action


@csrf_exempt
@require_http_methods(["HEAD", "POST"])
@transaction.atomic
def turnitin_callback(request):
    if request.method == 'HEAD':
        return HttpResponse(status=200)

    request_signature = request.META.get('HTTP_X_TURNITIN_SIGNATURE')
    request_event_type = request.META.get('HTTP_X_TURNITIN_EVENTTYPE')

    if not request_signature:
        return HttpResponseBadRequest("X-Turnitin-Signature header wasn't passed")

    if not request_event_type:
        return HttpResponseBadRequest("X-Turnitin-EventType header wasn't passed")

    sig = generate_hmac256_signature(request.body)
    if request_signature != sig:
        log_action('turnitin_callback', 'Invalid message signature: ' + request_signature + ' != ' + sig)
        return HttpResponseForbidden('Invalid request signature')

    try:
        data = json.loads(request.body)
    except ValueError:
        log_action('turnitin_callback', 'Invalid JSON body: ' + request.body)
        return HttpResponseBadRequest('Invalid JSON body')

    if request_event_type == 'SUBMISSION_COMPLETE':
        return _submission_complete_callback(data)
    elif request_event_type in ['SIMILARITY_COMPLETE', 'SIMILARITY_UPDATED']:
        return _similarity_complete_callback(data, request_event_type)

    return HttpResponse(status=200)


@login_required
def turnitin_report(request, ora_submission_id, submission_id):
    try:
        turnitin_submission = TurnitinSubmission.objects.get(id=submission_id, ora_submission_id=ora_submission_id)
    except TurnitinSubmission.DoesNotExist:
        return HttpResponseBadRequest('Submission not found')

    api_key = turnitin_submission.api_key
    if not api_key.is_active:
        return HttpResponseBadRequest("Api Key is inactive")

    try:
        turnitin_user = TurnitinUser.objects.get(user=turnitin_submission.user)
    except TurnitinUser.DoesNotExist:
        return HttpResponseBadRequest("Turnitin user doesn't exist")

    turnitin_api = TurnitinApi(api_key)
    status_code, viewer_url = turnitin_api.create_viewer_launch_url(turnitin_submission.turnitin_submission_id,
                                                                    turnitin_user)

    if viewer_url:
        return redirect(viewer_url)
    else:
        return HttpResponseBadRequest("Turnitin API error: HTTP code " + status_code)


@login_required
def turnitin_eula(request, api_key_id):
    try:
        turnitin_api_key = TurnitinApiKey.objects.get(id=api_key_id)
        if not turnitin_api_key.is_active:
            return HttpResponseBadRequest("Api Key is inactive")
    except TurnitinApiKey.DoesNotExist:
        return HttpResponseBadRequest("Api Key doesn't exist")

    turnitin_api = TurnitinApi(turnitin_api_key)
    eula_version, eula_url = turnitin_api.get_eula_version()
    if eula_version:
        return redirect(eula_url)
    else:
        return HttpResponseBadRequest("Turnitin API error")


def _submission_complete_callback(data):
    log_action('turnitin_callback', 'Process SUBMISSION_COMPLETE event', turnitin_submission_id=data['id'])

    try:
        turnitin_submission = TurnitinSubmission.objects.get(turnitin_submission_id=data['id'])
    except TurnitinSubmission.DoesNotExist:
        log_action('turnitin_callback', 'Turnitin submission not found', turnitin_submission_id=data['id'])
        return HttpResponseBadRequest('Submission not found')

    api_key = turnitin_submission.api_key
    if not api_key.is_active:
        return HttpResponseBadRequest("Api Key is inactive")

    turnitin_submission.status = data['status']
    turnitin_submission.set_data({'submission': data})
    turnitin_submission.save()

    if data['status'] != 'ERROR':
        transaction.on_commit(lambda: turnitin_generate_report.delay(data['id']))
    return HttpResponse(status=200)


def _similarity_complete_callback(data, event_type):
    log_action('turnitin_callback', 'Process ' + event_type + ' event', turnitin_submission_id=data['submission_id'])

    try:
        turnitin_submission = TurnitinSubmission.objects.get(turnitin_submission_id=data['submission_id'])
    except TurnitinSubmission.DoesNotExist:
        log_action('turnitin_callback', 'Turnitin submission not found', turnitin_submission_id=data['submission_id'])
        return HttpResponseBadRequest('submission not found')

    turnitin_submission.report_status = TurnitinReportStatus.COMPLETE
    turnitin_submission.update_data({'report': data})
    turnitin_submission.save()

    return HttpResponse(status=200)
