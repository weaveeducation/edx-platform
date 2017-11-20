"""Middleware classes for third_party_auth."""

import third_party_auth
from social_django.middleware import SocialAuthExceptionMiddleware

from . import pipeline
from opaque_keys.edx.keys import CourseKey
from courseware.courses import get_course_by_id
from student.models import CourseEnrollment
from django.http import HttpResponseRedirect
from util.request import course_id_from_url


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


class PipelineQuarantineMiddleware(object):
    """
    Middleware flushes the session if a user agent with a quarantined session
    attempts to leave the quarantined set of views.
    """

    def process_view(self, request, view_func, view_args, view_kwargs):  # pylint: disable=unused-argument
        """
        Check the session to see if we've quarantined the user to a particular
        step of the authentication pipeline; if so, look up which modules the
        user is allowed to browse to without breaking the pipeline. If the view
        that's been requested is outside those modules, then flush the session.

        In general, this middleware should be used in cases where allowing the
        user to exit the running pipeline would be undesirable, and where it'd
        be better to flush the session state rather than allow it. Pipeline
        quarantining is utilized by the Enterprise application to enforce
        collection of user consent for sharing data with a linked third-party
        authentication provider.
        """
        if not pipeline.running(request):
            return

        view_module = view_func.__module__
        quarantined_modules = request.session.get('third_party_auth_quarantined_modules')
        if quarantined_modules is not None and not any(view_module.startswith(mod) for mod in quarantined_modules):
            request.session.flush()


class SSOAuthMiddleware(object):

    sso_auto_enroll_cookie = 'SSO_COURSE_AUTO_ENROLL'

    def _check_sso_cookie_and_enroll(self, request):
        course_key = request.COOKIES.get(self.sso_auto_enroll_cookie, None)
        if course_key and request.user.is_authenticated():
            course_key_to_enroll = CourseKey.from_string(course_key)
            course_key_from_url = course_id_from_url(request.path)
            if course_key_to_enroll == course_key_from_url:
                course = get_course_by_id(course_key_to_enroll)
                if course and not CourseEnrollment.is_enrolled(request.user, course_key_to_enroll):
                    CourseEnrollment.enroll(request.user, course_key_to_enroll)

    def _remove_sso_cookie(self, request, response):
        course_key = request.COOKIES.get(self.sso_auto_enroll_cookie, None)
        course_key_from_url = course_id_from_url(request.path)
        if course_key and course_key_from_url and request.user.is_authenticated():
            response.delete_cookie(self.sso_auto_enroll_cookie)

    def process_request(self, request):
        if not third_party_auth.is_enabled():
            return None

        sso_login_as = request.GET.get('sso-login-as', None)
        if sso_login_as and not request.user.is_authenticated():
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
