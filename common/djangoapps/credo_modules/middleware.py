from credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer
from credo_modules.models import CourseUsage, CourseUsageLogEntry, usage_dt_now, get_student_properties
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
                course_key = CourseKey.from_string(course_id)
                position = int(request.POST.get('position', None)) - 1
                item = modulestore().get_item(UsageKey.from_string(block_id))
                if position is not None and hasattr(item, 'position'):
                    try:
                        child = item.get_children()[position]
                        student_properties = get_student_properties(request, course_key, child)
                        CourseUsage.update_block_usage(request, course_key, child.location, student_properties)
                    except IndexError:
                        pass

    def process_request(self, request):
        request.csrf_processing_done = True  # ignore CSRF check for the django REST framework

    def process_response(self, request, response):
        path = request.path
        path_data = path.split('/')

        if hasattr(request, 'user') and request.user.is_authenticated and len(path_data) > 2:
            course_id = None
            if path_data[1] == 'lti_provider':
                if len(path_data) > 3:
                    course_id = path_data[3]
            else:
                course_id = path_data[2]

            datetime_now = usage_dt_now()
            if course_id and not CourseUsage.is_viewed(request, course_id):
                try:
                    course_key = CourseKey.from_string(course_id)
                    CourseUsage.mark_viewed(request, course_id)
                    student_properties = get_student_properties(request, course_key)

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

                    CourseUsageLogEntry.add_new_log(request.user.id, str(course_key), 'course', 'course',
                                                    student_properties)
                except InvalidKeyError:
                    pass

            # Update usage of vertical blocks
            self._process_goto_position_urls(request, course_id, path_data)

        return response
