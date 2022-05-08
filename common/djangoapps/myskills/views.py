from django.contrib.auth.models import User
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions
from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from edx_rest_framework_extensions.auth.session.authentication import SessionAuthenticationAllowInactiveUser
from openedx.core.lib.api.authentication import BearerAuthenticationAllowInactiveUser
from lms.djangoapps.courseware.access import has_access
from lms.djangoapps.courseware.courses import get_course_with_access
from common.djangoapps.student.models import CourseEnrollment
from opaque_keys.edx.keys import CourseKey
from .services import MySkillsService
from .global_progress import get_global_skills_context, get_tags_global_data, get_sequential_block_questions,\
    MAX_COURSES_PER_USER
from .utils import get_student_name, convert_into_tree


def _get_student(request, course, student_id=None):
    if student_id is not None:
        try:
            student_id = int(student_id)
        except ValueError:
            raise Http404
    else:
        return request.user

    staff_access = bool(has_access(request.user, 'staff', course))
    if student_id and not staff_access:
        raise Http404

    try:
        student = User.objects.get(id=student_id)
    except User.DoesNotExist:
        raise Http404

    enrollment = CourseEnrollment.objects.filter(course_id=course.id, user_id=student.id, is_active=True).first()
    if not enrollment:
        raise Http404

    return student


def _get_student_and_course(request, course_key, student_id=None):
    course = get_course_with_access(request.user, 'load', course_key)
    student = _get_student(request, course, student_id=student_id)
    if request.user.id != student.id:
        # refetch the course as the assumed student
        course = get_course_with_access(request.user, 'load', course_key, check_if_enrolled=True)
    return student, course


class TagsSummaryView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student_and_course(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_tags_summary()
        return Response(data)


class TagsView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student_and_course(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_tags_all_data()
        return Response(data)


class TagsGlobalSummaryView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, student_id=None):
        user_id, student, course_ids, orgs, org = get_global_skills_context(request, student_id)
        context_data = {
            'orgs': sorted(orgs),
            'student_id': student.id,
            'student_name': get_student_name(student),
            'org': org,
        }

        if len(course_ids) > MAX_COURSES_PER_USER and len(orgs) > 1 and not org:
            context_data['error'] = 'specify_organization'
        else:
            tags = get_tags_global_data(student, orgs, course_ids, group_tags=False)
            tags_to_100 = sorted(tags, key=lambda k: "%03d_%s" % (k['percent_correct'], k['tag']))
            tags_from_100 = sorted(tags, key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))
            context_data.update({
                'top5tags': tags_from_100[:5],
                'lowest5tags': tags_to_100[:5],
            })
        return Response(context_data)


class TagsGlobalView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    @method_decorator(transaction.non_atomic_requests)
    def get(self, request, student_id=None):
        user_id, student, course_ids, orgs, org = get_global_skills_context(request, student_id)
        context_data = {
            'orgs': sorted(orgs),
            'student_id': student.id,
            'student_name': get_student_name(student),
            'org': org,
        }

        if len(course_ids) > MAX_COURSES_PER_USER and len(orgs) > 1 and not org:
            context_data['error'] = 'specify_organization'
        else:
            tags = get_tags_global_data(student, orgs, course_ids, group_tags=True)
            tags_assessments = [v.copy() for v in tags if v['tag_is_last']]
            tags = convert_into_tree(tags)
            tags_assessments = sorted(tags_assessments,
                                      key=lambda k: "%03d_%s" % (100 - k['percent_correct'], k['tag']))
            context_data.update({
                'tags': tags,
                'tags_assessments': tags_assessments
            })
        return Response(context_data)


def api_tag_global_data(request, student_id=None):
    tag_value = request.POST.get('tag')
    if not tag_value:
        raise Http404

    user_id, student, course_ids, orgs, org = get_global_skills_context(request, student_id)
    tags = get_tags_global_data(student, orgs, course_ids, tag_value=tag_value, group_tags=False,
                                group_by_course=True)
    return list(tags)[0] if len(tags) else None


def api_tag_section_data(request, student_id=None):
    tag_value = request.POST.get('tag')
    section_id = request.POST.get('section_id')
    if not tag_value or not section_id:
        raise Http404

    user_id, student, course_ids, orgs, org = get_global_skills_context(request, student_id)
    items = get_sequential_block_questions(request, section_id, tag_value, student)
    return items


class TagsTagDataView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    @method_decorator(transaction.non_atomic_requests)
    def post(self, request, student_id=None):
        tag = api_tag_global_data(request, student_id)
        return Response({'tag': tag})


class TagsTagSectionView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    @method_decorator(transaction.non_atomic_requests)
    def post(self, request, student_id=None):
        items = api_tag_section_data(request, student_id)
        return Response({'items': items})


class AssessmentSummaryView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student_and_course(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_assessment_summary(include_data_str=False)
        return Response(data)


class AssessmentView(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id, student_id=None):
        course_key = CourseKey.from_string(course_id)
        student, course = _get_student_and_course(request, course_key, student_id)
        service = MySkillsService(student, course)
        data = service.get_assessment_all_data(include_data_str=False)
        return Response(data)


class UserInfo(APIView):
    authentication_classes = (
        JwtAuthentication,
        BearerAuthenticationAllowInactiveUser,
        SessionAuthenticationAllowInactiveUser,
    )
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request, course_id=None, student_id=None):
        if student_id:
            try:
                student_id = int(student_id)
            except ValueError:
                return HttpResponseBadRequest('Invalid student ID')

        if course_id:
            course_key = CourseKey.from_string(course_id)
            course = get_course_with_access(request.user, 'load', course_key)
            student = _get_student(request, course, student_id=student_id)
        else:
            if request.user.is_superuser and student_id:
                student = User.objects.filter(id=student_id).first()
                if not student:
                    raise Http404("Student not found")
            else:
                student = request.user

        student_name = student.first_name + ' ' + student.last_name
        student_name = student_name.strip()
        if student_name:
            student_name = student_name + ' (' + student.email + ')'
        else:
            student_name = student.email

        return Response({
            'id': student.id,
            'student_name': student_name,
            'username': student.username,
            'email': student.email
        })


