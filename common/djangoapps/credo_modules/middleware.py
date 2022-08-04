from common.djangoapps.credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer
from common.djangoapps.credo_modules.models import CourseUsageHelper, CourseUsageLogEntry, get_student_properties,\
    update_unique_user_id_cookie, get_unique_user_id, get_inactive_orgs, UNIQUE_USER_ID_COOKIE
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponse
from openedx.core.djangoapps.site_configuration.helpers import get_value
from openedx.core.djangoapps.user_authn.cookies import set_logged_in_cookies
from edx_rest_framework_extensions.auth.jwt.cookies import jwt_cookie_header_payload_name, jwt_cookie_signature_name
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey, UsageKey
from xmodule.modulestore.django import modulestore

try:
    import Cookie
except ImportError:
    import http.cookies as Cookie
try:
    from django.utils.deprecation import MiddlewareMixin
except ImportError:
    MiddlewareMixin = object


# Add support for the SameSite attribute (obsolete when PY37 is unsupported).
# pylint: disable=protected-access
if 'samesite' not in Cookie.Morsel._reserved:
    Cookie.Morsel._reserved.setdefault('samesite', 'SameSite')


class RefererSaveMiddleware(MiddlewareMixin):
    def process_response(self, request, response):

        referer_url = get_request_referer_from_other_domain(request)
        if referer_url:
            saved_referer = get_saved_referer(request)
            if not saved_referer or saved_referer != referer_url:
                save_referer(request, response, referer_url)

        return response


class CourseUsageMiddleware(MiddlewareMixin):

    def _process_goto_position_urls(self, request, course_id, path_data):
        # handle URLs like
        # http://<lms_url>/courses/<course-id>/xblock/<block-id>/handler/xmodule_handler/goto_position
        if path_data[-1] == 'goto_position':
            block_id = None
            try:
                block_id = path_data[4]
            except IndexError:
                pass
            if block_id:
                course_key = CourseKey.from_string(course_id)
                position = request.POST.get('position', None)
                item = modulestore().get_item(UsageKey.from_string(block_id))
                if position is not None and hasattr(item, 'position'):
                    position = int(position) - 1
                    try:
                        child = item.get_children()[position]
                        student_properties = get_student_properties(request, course_key, child)
                        CourseUsageHelper.update_block_usage(request, course_key, child.location, student_properties)
                    except IndexError:
                        pass

    def _get_course_id_from_request(self, request):
        course_id = None
        path = request.path
        path_data = path.split('/')

        if len(path_data) <= 2:
            return None

        if path_data[1] == 'lti_provider':
            if len(path_data) > 3:
                course_id = path_data[3]
        elif path_data[1] == 'lti1p3_tool':
            usage_id = request.GET.get('block_id')
            if not usage_id and len(path_data) > 3:
                usage_id = path_data[3]
            if usage_id:
                try:
                    uk = UsageKey.from_string(usage_id)
                    course_id = str(uk.course_key)
                except InvalidKeyError:
                    pass
        else:
            course_id = path_data[2]

        return course_id if course_id else None

    def process_request(self, request):
        course_id = self._get_course_id_from_request(request)
        if course_id:
            try:
                course_key = CourseKey.from_string(course_id)
                deactivated_orgs = get_inactive_orgs()
                if course_key.org in deactivated_orgs and (not hasattr(request, 'user') or not request.user.is_superuser):
                    return HttpResponse("Course is inactive", status=404)
            except InvalidKeyError:
                pass

        request.csrf_processing_done = True  # ignore CSRF check for the django REST framework
        update_unique_user_id_cookie(request)

    def process_response(self, request, response):
        path = request.path
        path_data = path.split('/')

        if hasattr(request, 'user') and request.user.is_authenticated and len(path_data) > 2:
            course_id = self._get_course_id_from_request(request)

            sess_cookie_domain = get_value('SESSION_COOKIE_DOMAIN', settings.SESSION_COOKIE_DOMAIN)
            cookie_domain = sess_cookie_domain if sess_cookie_domain else None

            unique_user_id = get_unique_user_id(request)
            if unique_user_id and getattr(request, '_update_unique_user_id', False):
                response.set_cookie(UNIQUE_USER_ID_COOKIE, unique_user_id, path='/', domain=cookie_domain,
                                    secure=getattr(settings, 'SESSION_COOKIE_SECURE', False),
                                    samesite="None" if request.is_secure() else "Lax")

            if course_id and not CourseUsageHelper.is_viewed(request, course_id):
                try:
                    course_key = CourseKey.from_string(course_id)
                    CourseUsageHelper.mark_viewed(request, course_id)
                    student_properties = get_student_properties(request, course_key)
                    CourseUsageLogEntry.add_new_log(request.user.id, str(course_key), 'course', 'course',
                                                    student_properties)
                except InvalidKeyError:
                    pass

            # Update usage of vertical blocks
            self._process_goto_position_urls(request, course_id, path_data)

        return response


class LinkAccessOnlyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user and user.is_authenticated:
            hash_id = request.session.get('link_access_only')
            allowed_resources = ('.js', '.css', '.map', '.png', '.gif', '.jpg', '.jpeg', '.doc', '.docx')

            if hash_id and not request.path.endswith(allowed_resources):
                referer_url = request.META.get('HTTP_REFERER', '')
                url_allowed = '/supervisor/evaluation/' + hash_id
                if not request.is_ajax() or url_allowed not in referer_url:
                    logout(request)

        response = self.get_response(request)
        return response


class JwtCookiesMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        user_logged_in = getattr(request, '_user_logged_in', False)

        header_payload_cookie = request.COOKIES.get(jwt_cookie_header_payload_name())
        signature_cookie = request.COOKIES.get(jwt_cookie_signature_name())

        if user and user.is_authenticated and user_logged_in and (not header_payload_cookie or not signature_cookie):
            response = set_logged_in_cookies(request, response, user)
        return response
