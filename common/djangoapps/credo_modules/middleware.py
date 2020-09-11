from credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer
from credo_modules.models import CourseUsageHelper, CourseUsageLogEntry, get_student_properties,\
    update_unique_user_id_cookie, get_unique_user_id, get_inactive_orgs, UNIQUE_USER_ID_COOKIE
from django.conf import settings
from django.http import HttpResponse
from openedx.core.djangoapps.site_configuration.helpers import get_value
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
                save_referer(response, referer_url)

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
                position = int(request.POST.get('position', None)) - 1
                item = modulestore().get_item(UsageKey.from_string(block_id))
                if position is not None and hasattr(item, 'position'):
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
                                    secure=getattr(settings, 'SESSION_COOKIE_SECURE', False))

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


class CookiesSameSiteMiddleware(MiddlewareMixin):
    """
    Support for SameSite attribute in Cookies is implemented in Django 2.1 and won't
    be backported to Django 1.11.x.
    This middleware will be obsolete when your app will start using Django 2.1.
    """
    def process_response(self, request, response):
        protected_cookies = getattr(
            settings,
            'SESSION_COOKIE_SAMESITE_KEYS',
            set()
        ) or set()

        if not isinstance(protected_cookies, (list, set, tuple)):
            raise ValueError('SESSION_COOKIE_SAMESITE_KEYS should be a list, set or tuple.')

        protected_cookies = set(protected_cookies)
        protected_cookies |= {settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME}

        samesite_flag = getattr(
            settings,
            'SESSION_COOKIE_SAMESITE',
            None
        )

        if not samesite_flag:
            return response

        if samesite_flag.lower() not in {'lax', 'none', 'strict'}:
            raise ValueError('samesite must be "lax", "none", or "strict".')

        samesite_force_all = getattr(
            settings,
            'SESSION_COOKIE_SAMESITE_FORCE_ALL',
            False
        )
        if samesite_force_all:
            for cookie in response.cookies:
                response.cookies[cookie]['samesite'] = samesite_flag.lower().title()
        else:
            for cookie in protected_cookies:
                if cookie in response.cookies:
                    response.cookies[cookie]['samesite'] = samesite_flag.lower().title()

            # Update LTI1.3 auth cookie
            for cookie in response.cookies:
                if cookie.startswith('lti1p3'):
                    response.cookies[cookie]['samesite'] = samesite_flag.lower().title()

        return response
