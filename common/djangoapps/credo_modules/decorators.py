from lms.djangoapps.courseware.courses import get_course_by_id
from common.djangoapps.credo_modules.models import user_must_fill_additional_profile_fields
from django.shortcuts import reverse
from django.http import HttpResponseRedirect
from django.utils.http import urlquote
from opaque_keys.edx.keys import CourseKey


def credo_additional_profile(func):
    def wrapper(self, request, course_id, chapter=None, section=None, position=None):
        course = get_course_by_id(CourseKey.from_string(course_id))

        block = None
        if chapter and section:
            chapter_descriptor = course.get_child_by(lambda m: m.location.block_id == chapter)
            if chapter_descriptor:
                block = chapter_descriptor.get_child_by(lambda m: m.location.block_id == section)

        if user_must_fill_additional_profile_fields(course, request.user, block):
            next_page = urlquote(request.get_full_path())
            redirect_url = reverse('credo_modules_profile', kwargs={'course_id': str(course.id)})
            redirect_url = ''.join([redirect_url, '?next=', next_page])
            return HttpResponseRedirect(redirect_url)
        else:
            return func(self, request, course_id, chapter, section, position)
    return wrapper
