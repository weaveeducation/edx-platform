import json
import datetime
from credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer
from credo_modules.models import CourseUsage
from django.db.models import F
from django.db import IntegrityError
from opaque_keys import InvalidKeyError
from opaque_keys.edx.keys import CourseKey


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

    def process_response(self, request, response):
        path = request.path
        path_data = path.split('/')

        if hasattr(request, 'user') and request.user.is_authenticated() and len(path_data) > 2:
            course_id = path_data[2]

            course_usage_cookie = request.COOKIES.get(self.course_usage_cookie, '{}')
            try:
                course_usage_cookie_dict = json.loads(course_usage_cookie)
            except ValueError:
                course_usage_cookie_dict = {}

            datetime_now = datetime.datetime.now()
            if course_id and course_id not in course_usage_cookie_dict:
                try:
                    course_key = CourseKey.from_string(course_id)
                    course_usage_cookie_dict[course_id] = 1
                    response.set_cookie(self.course_usage_cookie, json.dumps(course_usage_cookie_dict))

                    try:
                        CourseUsage.objects.get(
                            course_id=course_key,
                            user_id=request.user.id,
                        )
                        CourseUsage.objects.filter(course_id=course_key, user_id=request.user.id) \
                            .update(last_usage_time=datetime_now, usage_count=F('usage_count') + 1)
                    except CourseUsage.DoesNotExist:
                        try:
                            cu = CourseUsage(
                                course_id=course_key,
                                user_id=request.user.id,
                                usage_count=1,
                                first_usage_time=datetime_now,
                                last_usage_time=datetime_now
                            )
                            cu.save()
                        except IntegrityError:
                            CourseUsage.objects.filter(course_id=course_key, user_id=request.user.id) \
                                .update(last_usage_time=datetime_now, usage_count=F('usage_count') + 1)
                except InvalidKeyError:
                    pass

        return response
