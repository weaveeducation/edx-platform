"""Middleware classes for third_party_auth."""

import urlparse

from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.translation import ugettext as _
from requests import HTTPError
from social_django.middleware import SocialAuthExceptionMiddleware

from student.helpers import get_next_url_for_login_page

import third_party_auth

from . import pipeline

from opaque_keys.edx.keys import CourseKey
from courseware.courses import get_course_by_id
from student.models import CourseEnrollment
from django.http import HttpResponseRedirect
from openedx.core.lib.request_utils import course_id_from_url


class ExceptionMiddleware(SocialAuthExceptionMiddleware):
    """Custom middleware that handles conditional redirection."""

    def get_redirect_uri(self, request, exception):
        # Fall back to django settings's SOCIAL_AUTH_LOGIN_ERROR_URL.
        redirect_uri = super(ExceptionMiddleware, self).get_redirect_uri(request, exception)

        # Safe because it's already been validated by
        # pipeline.parse_query_params. If that pipeline step ever moves later
        # in the pipeline stack, we'd need to validate this value because it
        # would be an injection point for attacker data.
        auth_entry = request.session.get(pipeline.AUTH_ENTRY_KEY)

        # Check if we have an auth entry key we can use instead
        if auth_entry and auth_entry in pipeline.AUTH_DISPATCH_URLS:
            redirect_uri = pipeline.AUTH_DISPATCH_URLS[auth_entry]

        return redirect_uri

    def process_exception(self, request, exception):
        """Handles specific exception raised by Python Social Auth eg HTTPError."""

        referer_url = request.META.get('HTTP_REFERER', '')
        if (referer_url and isinstance(exception, HTTPError) and
                exception.response.status_code == 502):
            referer_url = urlparse.urlparse(referer_url).path
            if referer_url == reverse('signin_user'):
                messages.error(request, _('Unable to connect with the external provider, please try again'),
                               extra_tags='social-auth')

                redirect_url = get_next_url_for_login_page(request)
                return redirect('/login?next=' + redirect_url)

        return super(ExceptionMiddleware, self).process_exception(request, exception)


class SSOAuthMiddleware(object):

    sso_auto_enroll_cookie = 'SSO_COURSE_AUTO_ENROLL'

    def _check_sso_cookie_and_enroll(self, request):
        course_key = request.COOKIES.get(self.sso_auto_enroll_cookie, None)
        if course_key and request.user.is_authenticated:
            course_key_to_enroll = CourseKey.from_string(course_key)
            course_key_from_url = course_id_from_url(request.path)
            if course_key_to_enroll == course_key_from_url:
                course = get_course_by_id(course_key_to_enroll)
                if course and not CourseEnrollment.is_enrolled(request.user, course_key_to_enroll):
                    CourseEnrollment.enroll(request.user, course_key_to_enroll)

    def _remove_sso_cookie(self, request, response):
        course_key = request.COOKIES.get(self.sso_auto_enroll_cookie, None)
        course_key_from_url = course_id_from_url(request.path)
        if course_key and course_key_from_url and request.user.is_authenticated:
            response.delete_cookie(self.sso_auto_enroll_cookie)

    def process_request(self, request):
        if not third_party_auth.is_enabled():
            return None

        sso_login_as = request.GET.get('sso-login-as', None)
        if sso_login_as and not request.user.is_authenticated:
            for enabled in third_party_auth.provider.Registry.displayed_for_login():
                if enabled.provider_id == sso_login_as:
                    login_url = pipeline.get_login_url(
                        sso_login_as,
                        pipeline.AUTH_ENTRY_LOGIN,
                        redirect_url=request.path,
                    )
                    redirect = HttpResponseRedirect(login_url)
                    course_key = course_id_from_url(request.path)
                    if course_key:
                        redirect.set_cookie(self.sso_auto_enroll_cookie, course_key)
                    return redirect

        self._check_sso_cookie_and_enroll(request)
        return None

    def process_response(self, request, response):
        if third_party_auth.is_enabled():
            self._remove_sso_cookie(request, response)
        return response
