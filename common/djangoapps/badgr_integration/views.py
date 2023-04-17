from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .api_client import BadgrApi
from .models import Assertion
from .service import issue_badge_assertion
from lms.djangoapps.courseware.block_render import get_module_by_usage_id
from lms.djangoapps.branding import api as branding_api
from opaque_keys.edx.keys import CourseKey, UsageKey
from opaque_keys import InvalidKeyError
from django.http import Http404
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from xmodule.modulestore.django import modulestore


class BadgesIssueView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request, course_id, usage_id):
        try:
            course_key = CourseKey.from_string(course_id)
        except InvalidKeyError:
            raise Http404

        with modulestore().bulk_operations(course_key):
            try:
                usage_key = UsageKey.from_string(usage_id)
            except InvalidKeyError:
                raise Http404

            instance, tracking_context = get_module_by_usage_id(
                request, course_id, str(usage_key)
            )

            result, badge_data, error = issue_badge_assertion(request.user, course_key, instance)
            if badge_data:
                badge_data['platform_logo_url'] = branding_api.get_logo_url(request.is_secure())

            return Response({
                'result': result,
                'data': badge_data,
                'error': error
            })


@login_required
def open_badge(request, assertion_id):
    assertion = Assertion.objects.filter(user=request.user, external_id=assertion_id).first()
    if assertion:
        api_client = BadgrApi()
        badge_data = api_client.get_assertion(assertion_id)
        return redirect(badge_data['openBadgeId'])
    else:
        raise Http404


class BadgesView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id):
        result = []

        assertions = Assertion.objects.filter(
            user=request.user, course_id=course_id).select_related('badge').order_by('-created_at')
        for a in assertions:
            result.append({
                'assertion_external_id': a.external_id,
                'assertion_image_url': a.image_url,
                'assertion_url': a.url,
                'badge_title': a.badge.title,
                'badge_description': a.badge.description,
                'badge_url': a.badge.url,
                'created': str(a.created_at) if a.created_at else None
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
        courses = []
        result = []

        assertions = Assertion.objects.filter(user=request.user).order_by('-created_at')
        if len(assertions) > 0:
            for a in assertions:
                if a.course_id not in courses:
                    course_key = CourseKey.from_string(a.course_id)
                    if not org or org == course_key.org:
                        courses.append(a.course_id)
                        result.append({
                            'course_id': a.course_id,
                            'org': course_key.org,
                            'course': course_key.course,
                            'run': course_key.run
                        })
        return Response(result)
