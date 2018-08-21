import json
import datetime
import uuid
from credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer
from credo_modules.models import CourseUsage, get_unique_user_id, UNIQUE_USER_ID_COOKIE
from django.db import IntegrityError, transaction
from django.db.models import F
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey, UsageKey
from xmodule.modulestore.django import modulestore


class RefererSaveMiddleware(object):
    def process_response(self, request, response):

        referer_url = get_request_referer_from_other_domain(request)
        if referer_url:
            saved_referer = get_saved_referer(request)
            if not saved_referer or saved_referer != referer_url:
                save_referer(response, referer_url)

        return response


class CourseUsageMiddleware(object):
    course_usage_cookie = 'credo-course-usage'

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
                position = int(request.POST.get('position', None)) - 1
                item = modulestore().get_item(UsageKey.from_string(block_id))
                if position is not None and hasattr(item, 'position'):
                    try:
                        child = item.get_children()[position]
                        CourseUsage.update_block_usage(request, CourseKey.from_string(course_id), child.location)
                    except IndexError:
                        pass

    def process_request(self, request):
        course_usage_cookie_id = get_unique_user_id(request)
        if not course_usage_cookie_id:
            request.COOKIES[UNIQUE_USER_ID_COOKIE] = unicode(uuid.uuid4())
            request.COOKIES['course_usage_cookie_was_set'] = '1'

    def process_response(self, request, response):
        path = request.path
        path_data = path.split('/')

        if hasattr(request, 'user') and request.user.is_authenticated() and len(path_data) > 2:
            course_id = None
            if path_data[1] == 'lti_provider':
                if len(path_data) > 3:
                    course_id = path_data[3]
            else:
                course_id = path_data[2]

            user_id = int(request.user.id)

            user_id_from_cookie = None
            course_usage_cookie_dict = {}
            course_usage_cookie = request.COOKIES.get(self.course_usage_cookie, '{}')

            unique_user_id = get_unique_user_id(request)

            if request.COOKIES.get('course_usage_cookie_was_set', False) and unique_user_id:
                response.set_cookie(UNIQUE_USER_ID_COOKIE, unique_user_id)

            try:
                course_usage_cookie_arr = course_usage_cookie.split('|')
                if len(course_usage_cookie_arr) > 1:
                    try:
                        user_id_from_cookie = int(course_usage_cookie_arr[1])
                    except ValueError:
                        pass

                    if user_id_from_cookie and user_id != user_id_from_cookie:
                        course_usage_cookie_dict = {}
                    else:
                        course_usage_cookie_dict = json.loads(course_usage_cookie_arr[0])
                else:
                    course_usage_cookie_dict = json.loads(course_usage_cookie)
            except ValueError:
                pass

            datetime_now = datetime.datetime.now()
            if course_id and course_id not in course_usage_cookie_dict:
                try:
                    course_key = CourseKey.from_string(course_id)
                    course_usage_cookie_dict[course_id] = 1
                    response.set_cookie(self.course_usage_cookie,
                                        json.dumps(course_usage_cookie_dict) + '|' + str(user_id))

                    try:
                        CourseUsage.objects.get(
                            course_id=course_key,
                            user_id=request.user.id,
                            block_type='course',
                            block_id='course'
                        )
                        CourseUsage.objects.filter(course_id=course_key, user_id=request.user.id,
                                                   block_type='course', block_id='course') \
                            .update(last_usage_time=datetime_now, usage_count=F('usage_count') + 1)
                    except CourseUsage.DoesNotExist:
                        try:
                            with transaction.atomic():
                                cu = CourseUsage(
                                    course_id=course_key,
                                    user_id=request.user.id,
                                    usage_count=1,
                                    block_type='course',
                                    block_id='course',
                                    first_usage_time=datetime_now,
                                    last_usage_time=datetime_now
                                )
                                cu.save()
                        except IntegrityError:
                            CourseUsage.objects.filter(course_id=course_key, user_id=request.user.id,
                                                       block_type='course', block_id='course') \
                                .update(last_usage_time=datetime_now, usage_count=F('usage_count') + 1)
                except InvalidKeyError:
                    pass

            # Update usage of vertical blocks
            self._process_goto_position_urls(request, course_id, path_data)

        return response
