from django.utils.http import urlquote
from util.request import course_id_from_url
from courseware.courses import get_course_by_id
from student.models import CourseEnrollment
from django.core.urlresolvers import reverse
from django.http import HttpResponseRedirect
from credo.auth_helper import get_request_referer_from_other_domain, get_saved_referer, save_referer
from credo_modules.models import CredoModulesUserProfile
from credo_modules.utils import additional_profile_fields_hash


class RefererSaveMiddleware(object):

    def process_response(self, request, response):

        referer_url = get_request_referer_from_other_domain(request)
        if referer_url:
            saved_referer = get_saved_referer(request)
            if not saved_referer or saved_referer != referer_url:
                save_referer(response, referer_url)

        return response


class CheckCredoAdditionalProfile(object):

    def process_request(self, request):
        if not request.path.startswith('/credo_modules/profile') and request.user.is_authenticated:
            course_key = course_id_from_url(request.path)
            if course_key:
                course = get_course_by_id(course_key)
                if course.credo_additional_profile_fields and CourseEnrollment.is_enrolled(request.user, course_key):
                    fields_version = additional_profile_fields_hash(course.credo_additional_profile_fields)
                    profiles = CredoModulesUserProfile.objects.filter(user=request.user, course_id=course_key)
                    if len(profiles) == 0 or profiles[0].fields_version != fields_version:
                        next_page = urlquote(request.get_full_path())
                        redirect_url = reverse('credo_modules_profile', kwargs={'course_id': unicode(course_key)})
                        redirect_url = ''.join([redirect_url, '?next=', next_page])
                        return HttpResponseRedirect(redirect_url)
        return None
