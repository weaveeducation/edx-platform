"""
Middleware for the courseware app
"""

from django.shortcuts import redirect
from django.core.urlresolvers import reverse

from courseware.courses import UserNotEnrolled
from credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer


class RedirectUnenrolledMiddleware(object):
    """
    Catch UserNotEnrolled errors thrown by `get_course_with_access` and redirect
    users to the course about page
    """
    def process_exception(self, _request, exception):
        if isinstance(exception, UserNotEnrolled):
            course_key = exception.course_key
            return redirect(
                reverse(
                    'courseware.views.course_about',
                    args=[course_key.to_deprecated_string()]
                )
            )


class RefererSaveMiddleware(object):

    def process_response(self, request, response):

        referer_url = get_request_referer_from_other_domain(request)
        if referer_url:
            saved_referer = get_saved_referer(request)
            if not saved_referer or saved_referer != referer_url:
                save_referer(response, referer_url)

        return response
