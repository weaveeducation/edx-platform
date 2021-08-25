from django.http import Http404
from django.contrib.auth.models import User
from rest_framework.views import APIView
from rest_framework.response import Response
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from lms.djangoapps.courseware.access import has_access
from lms.djangoapps.courseware.courses import get_course_with_access
from opaque_keys.edx.keys import CourseKey
from .services import MySkillsService


def _get_student(request, course_key, student_id=None):
    course = get_course_with_access(request.user, 'load', course_key)

    if student_id is not None:
        try:
            student_id = int(student_id)
        except ValueError:
            raise Http404
    else:
        return request.user, course

    staff_access = bool(has_access(request.user, 'staff', course))
    if student_id and not staff_access:
        raise Http404

    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        raise Http404

    course = get_course_with_access(request.user, 'load', course_key, check_if_enrolled=True)
    return student, course


class TagsSummaryView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_tags_summary()
        return Response(data)


class TagsView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_tags_all_data()
        return Response(data)


class AssessmentSummaryView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_assessment_summary(include_data_str=False)
        return Response(data)


class AssessmentView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_assessment_all_data()
        return Response(data)
