import json
from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.views.generic.base import View
from django.utils.decorators import method_decorator
from django.contrib.auth.decorators import login_required
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from opaque_keys.edx.keys import CourseKey, UsageKey
from lms.djangoapps.courseware.views.views import render_xblock
from lms.djangoapps.supervisor_evaluation.utils import get_course_block_with_survey
from common.djangoapps.edxmako.shortcuts import render_to_response
from common.djangoapps.credo_modules.models import SupervisorEvaluationInvitation
from common.djangoapps.credo_modules.views import StudentProfileField, validate_profile_fields_post
from common.djangoapps.myskills.services import get_block_student_progress
from xmodule.modulestore.django import modulestore


def render_supervisor_evaluation_block(request, hash_id):
    invitation = SupervisorEvaluationInvitation.objects.filter(url_hash=hash_id).first()
    if not invitation:
        raise Http404("Invalid page link")

    dt_now = timezone.now()
    if invitation.expiration_date and dt_now > invitation.expiration_date:
        return HttpResponseForbidden("Link lifetime has expired")

    course_key = CourseKey.from_string(invitation.course_id)
    usage_key = UsageKey.from_string(invitation.evaluation_block_id)

    with modulestore().bulk_operations(course_key):
        supervisor_evaluation_xblock = modulestore().get_item(usage_key)
        survey_sequential_block = get_course_block_with_survey(course_key, supervisor_evaluation_xblock)

    if not survey_sequential_block:
        return HttpResponseForbidden("Block with questions not found")

    if not request.user.is_authenticated or request.user.id != invitation.student.id:
        login(request, invitation.student, backend=settings.AUTHENTICATION_BACKENDS[0])
        request.session['link_access_only'] = hash_id
        request.session.modified = True

    if supervisor_evaluation_xblock.profile_fields and not invitation.profile_fields:
        fields = StudentProfileField.init_from_fields(supervisor_evaluation_xblock.profile_fields)
        context = {
            'fields': fields.values(),
            'redirect_url': '',
            'form_submit_url': reverse('supervisor_evaluation_profile', kwargs={'hash_id': hash_id}),
            'disable_accordion': True,
            'allow_iframing': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'disable_preview_menu': True,
            'link_access_hash': hash_id
        }
        resp = render_to_response("credo_additional_profile.html", context)
    else:
        resp = render_xblock(request, str(survey_sequential_block.location), check_if_enrolled=False,
                             show_bookmark_button=False, link_access_hash=hash_id)

    resp.set_cookie('supervisor-link-hash', hash_id, secure=getattr(settings, 'SESSION_COOKIE_SECURE', False))
    return resp


class SupervisorEvaluationProfileView(View):

    @method_decorator(login_required)
    @method_decorator(transaction.atomic)
    def post(self, request, hash_id):
        invitation = SupervisorEvaluationInvitation.objects.filter(url_hash=hash_id).first()
        if not invitation:
            return JsonResponse({}, status=404)

        usage_key = UsageKey.from_string(invitation.evaluation_block_id)
        supervisor_evaluation_xblock = modulestore().get_item(usage_key)

        if not supervisor_evaluation_xblock.profile_fields:
            return JsonResponse({}, status=404)

        to_save_fields, errors = validate_profile_fields_post(request, supervisor_evaluation_xblock.profile_fields)
        if errors:
            return JsonResponse(errors, status=400)
        else:
            to_save_fields_json = json.dumps(to_save_fields, sort_keys=True)
            invitation.profile_fields = to_save_fields_json
            invitation.save()
            return JsonResponse({"success": True})


class SurveyResults(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, hash_id=None):
        timezone_offset = request.GET.get('timezone_offset', None)
        if timezone_offset is not None:
            timezone_offset = int(timezone_offset)

        invitation = SupervisorEvaluationInvitation.objects.filter(url_hash=hash_id).first()
        if not invitation:
            return JsonResponse({}, status=404)

        result = {
            'form_data': json.loads(invitation.profile_fields) if invitation.profile_fields else None
        }

        course_key = CourseKey.from_string(invitation.course_id)
        usage_key = UsageKey.from_string(invitation.evaluation_block_id)

        with modulestore().bulk_operations(course_key):
            supervisor_evaluation_xblock = modulestore().get_item(usage_key)
            result['form_fields_config'] = None

            survey_sequential_block = get_course_block_with_survey(course_key, supervisor_evaluation_xblock)
            result['block_data'] = get_block_student_progress(
                request, invitation.course_id, str(survey_sequential_block.location), timezone_offset)

        return Response(result)
