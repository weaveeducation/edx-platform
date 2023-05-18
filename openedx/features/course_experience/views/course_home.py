"""
Views for the course home page.
"""

from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required

from common.djangoapps.student.models import CourseEnrollment
from common.djangoapps.util.views import ensure_valid_course_key
from xmodule.modulestore.django import modulestore
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.user_api.accounts.utils import is_user_credo_anonymous
from openedx.features.course_experience.url_helpers import get_learning_mfe_home_url


@ensure_valid_course_key
@login_required
def outline_tab(request, course_id):
    """Simply redirects to the MFE outline tab, as this legacy view for the course home/outline no longer exists."""
    course_key = CourseKey.from_string(course_id)
    with modulestore().bulk_operations(course_key):
        course_obj = modulestore().get_course(course_key, depth=0)
        if request.user.is_authenticated and is_user_credo_anonymous(request.user) \
            and course_obj and course_obj.allow_anonymous_access:
            CourseEnrollment.enroll(request.user, course_key)
    return redirect(get_learning_mfe_home_url(course_key=course_id, url_fragment='home', params=request.GET))
