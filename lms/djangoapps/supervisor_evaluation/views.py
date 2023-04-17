import json
from collections import OrderedDict
from django.conf import settings
from django.contrib.auth import login, get_user_model
from django.db import transaction
from django.http import Http404, HttpResponse, HttpResponseForbidden, HttpResponseBadRequest, JsonResponse
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
from lms.djangoapps.courseware.utils import get_block_children, CREDO_GRADED_ITEM_CATEGORIES, get_answer_and_correctness
from lms.djangoapps.courseware.block_render import get_module_by_usage_id
from lms.djangoapps.courseware.user_state_client import DjangoXBlockUserStateClient
from lms.djangoapps.supervisor_evaluation.tasks import generate_supervisor_pdf
from lms.djangoapps.supervisor_evaluation.utils import get_course_block_with_survey
from common.djangoapps.edxmako.shortcuts import render_to_response
from common.djangoapps.credo_modules.models import SupervisorEvaluationInvitation
from common.djangoapps.credo_modules.views import StudentProfileField, validate_profile_fields_post
from common.djangoapps.credo_modules.utils import get_skills_mfe_url
from xmodule.modulestore.django import modulestore
from openedx.core.djangoapps.user_authn.views.custom import register_login_and_enroll_anonymous_user


User = get_user_model()


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

    supervisor_user = None
    if not request.user.is_authenticated or request.user.id != invitation.student.id:
        if invitation.supervisor_user_id is None:
            supervisor_user = register_login_and_enroll_anonymous_user(
                request, course_key, email_domain='supervisor.weaveeducation.com')
        else:
            supervisor_user = User.objects.filter(id=invitation.supervisor_user_id).first()
            if not supervisor_user:
                supervisor_user = register_login_and_enroll_anonymous_user(
                    request, course_key, email_domain='supervisor.weaveeducation.com')
            elif not request.user.is_authenticated or request.user.id != supervisor_user.id:
                login(request, supervisor_user, backend=settings.AUTHENTICATION_BACKENDS[0])

        if supervisor_user and supervisor_user.id != invitation.supervisor_user_id:
            invitation.supervisor_user_id = supervisor_user.id
            invitation.save()

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

    resp.set_cookie('supervisor-link-hash', hash_id,
                    secure=getattr(settings, 'SESSION_COOKIE_SECURE', False),
                    samesite="None" if request.is_secure() else "Lax")
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
        user_id = request.user.id

        invitation = SupervisorEvaluationInvitation.objects.filter(url_hash=hash_id, student_id=user_id).first()
        if not invitation:
            return JsonResponse({}, status=404)

        course_key = CourseKey.from_string(invitation.course_id)
        profile_fields = json.loads(invitation.profile_fields) if invitation.profile_fields else None

        result = {
            'form_data': profile_fields,
            'common': {
                'org': course_key.org,
                'course': course_key.course,
                'run': course_key.run
            }
        }

        course_key = CourseKey.from_string(invitation.course_id)
        usage_key = UsageKey.from_string(invitation.evaluation_block_id)
        graded_categories = CREDO_GRADED_ITEM_CATEGORIES[:]
        graded_categories.extend(['survey', 'freetextresponse'])

        with modulestore().bulk_operations(course_key):
            course = modulestore().get_course(course_key)
            supervisor_evaluation_xblock = modulestore().get_item(usage_key)
            result['form_fields_config'] = []
            result['common']['report_name'] = supervisor_evaluation_xblock.display_name

            if supervisor_evaluation_xblock.profile_fields:
                for field_key, field_value in supervisor_evaluation_xblock.profile_fields.items():
                    if not field_value.get('info', False):
                        field_value_upd = field_value.copy()
                        field_value_upd['key'] = field_key
                        field_value_upd['value'] = profile_fields.get(field_key, None) if profile_fields else None
                        result['form_fields_config'].append(field_value_upd)
                result['form_fields_config'] = sorted(result['form_fields_config'], key=lambda k: k.get('order', 0))

            survey_items = []
            survey_sequential_block = get_course_block_with_survey(course_key, supervisor_evaluation_xblock)
            block, tracking_context = get_module_by_usage_id(
                request, str(course_key), str(survey_sequential_block.location), course=course)
            block_children = get_block_children(block, '', add_correctness=False)

            problem_locations = []
            for problem_loc, problem_details in block_children.items():
                problem_locations.append(UsageKey.from_string(problem_loc))

            user_state_client = DjangoXBlockUserStateClient(request.user)
            user_state_dict = {}

            if problem_locations:
                user_state_dict = user_state_client.get_all_blocks(request.user, course_key, problem_locations)

            for problem_loc, problem_details in block_children.items():
                category = problem_details['category']
                if category in graded_categories:
                    item = problem_details['data']
                    survey_item = {
                        'id': str(item.location),
                        'category': problem_details['category'],
                        'display_name': item.display_name,
                        'parent_name': problem_details['parent_name'],
                    }

                    submission_uuid = None
                    if problem_details['category'] == 'openassessment':
                        submission_uuid = item.submission_uuid
                    answer, tmp_correctness = get_answer_and_correctness(
                        user_state_dict, None, problem_details['category'],
                        item, str(item.location), submission_uuid=submission_uuid)
                    od = OrderedDict(sorted(answer.items())) if answer else {}

                    if problem_details['category'] == 'survey':
                        survey_item.update({
                            'display_name': item.block_name,
                            'questions': [{'id': i[0], 'label': i[1]['label']} for i in item.questions],
                            'possible_answers': [{'id': i[0], 'label': i[1]} for i in item.answers],
                            'user_answers': item.choices
                        })
                    elif problem_details['category'] == 'freetextresponse':
                        survey_item.update({
                            'question_text': item.prompt,
                            'answer': item.student_answer
                        })
                    else:
                        answers = od.values() if answer else []
                        survey_item.update({
                            'question_text': problem_details['question_text'],
                            'question_text_safe': problem_details['question_text_safe'],
                            'question_text_list': problem_details['question_text_list'],
                            'answer': '; '.join(answers) if answer else None,
                            'answers_list': od.values() if answer else [],
                            'possible_options': problem_details.get('possible_options', None),
                        })
                    survey_items.append(survey_item)
            result['survey_items'] = survey_items

        return Response(result)


class ReportsView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id):
        user_id = request.user.id
        course_key = CourseKey.from_string(course_id)
        result = []

        invitations = SupervisorEvaluationInvitation.objects.filter(
            course_id=course_id, survey_finished=True, student_id=user_id).order_by('-created')
        if len(invitations) > 0:
            with modulestore().bulk_operations(course_key):
                for invitation in invitations:
                    evaluation_usage_key = UsageKey.from_string(invitation.evaluation_block_id)
                    supervisor_evaluation_xblock = modulestore().get_item(evaluation_usage_key)
                    result.append({
                        'title': supervisor_evaluation_xblock.display_name,
                        'url_hash': invitation.url_hash,
                        'created': str(invitation.created)
                    })

        return Response(result)


class CoursesView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        org = request.GET.get('org')
        user_id = request.user.id
        courses = []
        result = []

        invitations = SupervisorEvaluationInvitation.objects.filter(
            survey_finished=True, student_id=user_id).order_by('-created')
        if len(invitations) > 0:
            for invitation in invitations:
                if invitation.course_id not in courses:
                    course_key = CourseKey.from_string(invitation.course_id)
                    if not org or org == course_key.org:
                        courses.append(invitation.course_id)
                        result.append({
                            'course_id': invitation.course_id,
                            'org': course_key.org,
                            'course': course_key.course,
                            'run': course_key.run
                        })
        return Response(result)


@login_required
def generate_pdf_report(request, hash_id):
    skills_mfe_url = get_skills_mfe_url()
    if not skills_mfe_url:
        raise Http404("MFE url is unavailable")

    user_id = request.user.id
    invitation = SupervisorEvaluationInvitation.objects.filter(url_hash=hash_id, student_id=user_id).first()
    if not invitation:
        raise Http404("Invalid invitation link")

    if not invitation.survey_finished:
        return HttpResponseBadRequest('Survey is not finished yet')

    try:
        pdf_bytes = generate_supervisor_pdf(skills_mfe_url, hash_id, request.user)
        response = HttpResponse(content=pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = 'attachment; filename="report-' + hash_id + '.pdf"'
        return response
    except Exception as e:
        return HttpResponseBadRequest('Error: ' + str(e))
