"""
Course API Views
"""

import json

from django.core.exceptions import ValidationError
from django.core.paginator import InvalidPage
from edx_django_utils.monitoring import function_trace
from edx_rest_framework_extensions.paginators import NamespacedPageNumberPagination
from rest_framework.exceptions import NotFound
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.throttling import UserRateThrottle
from common.djangoapps.credo_modules.models import Organization, OrganizationType
from common.djangoapps.credo_modules.course_access_handler import CourseAccessHandler

from openedx.core.lib.api.view_utils import DeveloperErrorViewMixin, view_auth_classes
from openedx.core.djangoapps.content.block_structure.tasks import update_course_structure,\
    _update_sequential_block_in_vertica
from opaque_keys.edx.keys import CourseKey

from . import USE_RATE_LIMIT_2_FOR_COURSE_LIST_API, USE_RATE_LIMIT_10_FOR_COURSE_LIST_API
from .api import course_detail, list_course_keys, list_courses
from .forms import CourseDetailGetForm, CourseIdListGetForm, CourseListGetForm
from .serializers import CourseDetailSerializer, CourseKeySerializer, CourseSerializer

from edx_rest_framework_extensions.auth.jwt.authentication import JwtAuthentication
from rest_framework.views import APIView
from rest_framework.response import Response
from openedx.core.lib.api.authentication import OAuth2AuthenticationAllowInactiveUser
from openedx.core.lib.api.permissions import ApiKeyHeaderPermissionIsAuthenticated
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.credo_modules.models import get_inactive_orgs


@view_auth_classes(is_authenticated=False)
class CourseDetailView(DeveloperErrorViewMixin, RetrieveAPIView):
    """
    **Use Cases**

        Request details for a course

    **Example Requests**

        GET /api/courses/v1/courses/{course_key}/

    **Response Values**

        Body consists of the following fields:

        * effort: A textual description of the weekly hours of effort expected
            in the course.
        * end: Date the course ends, in ISO 8601 notation
        * enrollment_end: Date enrollment ends, in ISO 8601 notation
        * enrollment_start: Date enrollment begins, in ISO 8601 notation
        * id: A unique identifier of the course; a serialized representation
            of the opaque key identifying the course.
        * media: An object that contains named media items.  Included here:
            * course_image: An image to show for the course.  Represented
              as an object with the following fields:
                * uri: The location of the image
        * name: Name of the course
        * number: Catalog number of the course
        * org: Name of the organization that owns the course
        * overview: A possibly verbose HTML textual description of the course.
            Note: this field is only included in the Course Detail view, not
            the Course List view.
        * short_description: A textual description of the course
        * start: Date the course begins, in ISO 8601 notation
        * start_display: Readably formatted start of the course
        * start_type: Hint describing how `start_display` is set. One of:
            * `"string"`: manually set by the course author
            * `"timestamp"`: generated from the `start` timestamp
            * `"empty"`: no start date is specified
        * pacing: Course pacing. Possible values: instructor, self
        * certificate_available_date (optional): Date the certificate will be available,
            in ISO 8601 notation if the `certificates.auto_certificate_generation`
            waffle switch is enabled

        Deprecated fields:

        * blocks_url: Used to fetch the course blocks
        * course_id: Course key (use 'id' instead)

    **Parameters:**

        username (optional):
            The username of the specified user for whom the course data
            is being accessed. The username is not only required if the API is
            requested by an Anonymous user.

    **Returns**

        * 200 on success with above fields.
        * 400 if an invalid parameter was sent or the username was not provided
          for an authenticated request.
        * 403 if a user who does not have permission to masquerade as
          another user specifies a username other than their own.
        * 404 if the course is not available or cannot be seen.

        Example response:

            {
                "blocks_url": "/api/courses/v1/blocks/?course_id=edX%2Fexample%2F2012_Fall",
                "media": {
                    "course_image": {
                        "uri": "/c4x/edX/example/asset/just_a_test.jpg",
                        "name": "Course Image"
                    }
                },
                "description": "An example course.",
                "end": "2015-09-19T18:00:00Z",
                "enrollment_end": "2015-07-15T00:00:00Z",
                "enrollment_start": "2015-06-15T00:00:00Z",
                "course_id": "edX/example/2012_Fall",
                "name": "Example Course",
                "number": "example",
                "org": "edX",
                "overview: "<p>A verbose description of the course.</p>"
                "start": "2015-07-17T12:00:00Z",
                "start_display": "July 17, 2015",
                "start_type": "timestamp",
                "pacing": "instructor",
                "certificate_available_date": "2015-08-14T00:00:00Z"
            }
    """

    serializer_class = CourseDetailSerializer

    def get_object(self):
        """
        Return the requested course object, if the user has appropriate
        permissions.
        """
        requested_params = self.request.query_params.copy()
        requested_params.update({'course_key': self.kwargs['course_key_string']})
        form = CourseDetailGetForm(requested_params, initial={'requesting_user': self.request.user})
        if not form.is_valid():
            raise ValidationError(form.errors)

        return course_detail(
            self.request,
            form.cleaned_data['username'],
            form.cleaned_data['course_key'],
        )


class CourseListUserThrottle(UserRateThrottle):
    """Limit the number of requests users can make to the course list API."""
    # The course list endpoint is likely being inefficient with how it's querying
    # various parts of the code and can take courseware down, it needs to be rate
    # limited until optimized. LEARNER-5527

    THROTTLE_RATES = {
        'user': '20/minute',
        'staff': '40/minute',
    }

    def check_for_switches(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        if USE_RATE_LIMIT_2_FOR_COURSE_LIST_API.is_enabled():
            self.THROTTLE_RATES = {
                'user': '2/minute',
                'staff': '10/minute',
            }
        elif USE_RATE_LIMIT_10_FOR_COURSE_LIST_API.is_enabled():
            self.THROTTLE_RATES = {
                'user': '10/minute',
                'staff': '20/minute',
            }

    def allow_request(self, request, view):
        self.check_for_switches()
        # Use a special scope for staff to allow for a separate throttle rate
        user = request.user
        if user.is_authenticated and (user.is_staff or user.is_superuser):
            self.scope = 'staff'
            self.rate = self.get_rate()
            self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)


class LazyPageNumberPagination(NamespacedPageNumberPagination):
    """
    NamespacedPageNumberPagination that works with a LazySequence queryset.

    The paginator cache uses ``@cached_property`` to cache the property values for
    count and num_pages.  It assumes these won't change, but in the case of a
    LazySquence, its count gets updated as we move through it.  This class clears
    the cached property values before reporting results so they will be recalculated.

    """

    @function_trace('get_paginated_response')
    def get_paginated_response(self, data):
        # Clear the cached property values to recalculate the estimated count from the LazySequence
        del self.page.paginator.__dict__['count']
        del self.page.paginator.__dict__['num_pages']

        # Paginate queryset function is using cached number of pages and sometime after
        # deleting from cache when we recalculate number of pages are different and it raises
        # EmptyPage error while accessing the previous page link. So we are catching that exception
        # and raising 404. For more detail checkout PROD-1222
        page_number = self.request.query_params.get(self.page_query_param, 1)
        try:
            self.page.paginator.validate_number(page_number)
        except InvalidPage as exc:
            msg = self.invalid_page_message.format(
                page_number=page_number, message=str(exc)
            )
            self.page.number = self.page.paginator.num_pages
            raise NotFound(msg)  # lint-amnesty, pylint: disable=raise-missing-from

        return super().get_paginated_response(data)

    @function_trace('pagination_paginate_queryset')
    def paginate_queryset(self, queryset, request, view=None):
        """
        Paginate a queryset if required, either returning a
        page object, or `None` if pagination is not configured for this view.

        This is copied verbatim from upstream with added function traces.
        https://github.com/encode/django-rest-framework/blob/c6e24521dab27a7af8e8637a32b868ffa03dec2f/rest_framework/pagination.py#L191
        """
        with function_trace('pagination_paginate_queryset_get_page_size'):
            page_size = self.get_page_size(request)
            if not page_size:
                return None

        with function_trace('pagination_paginate_queryset_construct_paginator_instance'):
            paginator = self.django_paginator_class(queryset, page_size)

        with function_trace('pagination_paginate_queryset_get_page_number'):
            page_number = request.query_params.get(self.page_query_param, 1)

        if page_number in self.last_page_strings:
            page_number = paginator.num_pages

        with function_trace('pagination_paginate_queryset_get_page'):
            try:
                self.page = paginator.page(page_number)  # lint-amnesty, pylint: disable=attribute-defined-outside-init
            except InvalidPage as exc:
                msg = self.invalid_page_message.format(
                    page_number=page_number, message=str(exc)
                )
                raise NotFound(msg)  # lint-amnesty, pylint: disable=raise-missing-from

        with function_trace('pagination_paginate_queryset_get_num_pages'):
            if paginator.num_pages > 1 and self.template is not None:
                # The browsable API should display pagination controls.
                self.display_page_controls = True

        self.request = request  # lint-amnesty, pylint: disable=attribute-defined-outside-init

        with function_trace('pagination_paginate_queryset_listify_page'):
            page_list = list(self.page)

        return page_list


@view_auth_classes(is_authenticated=False)
class CourseListView(DeveloperErrorViewMixin, ListAPIView):
    """
    **Use Cases**

        Request information on all courses visible to the specified user.

    **Example Requests**

        GET /api/courses/v1/courses/

    **Response Values**

        Body comprises a list of objects as returned by `CourseDetailView`.

    **Parameters**

        search_term (optional):
            Search term to filter courses (used by ElasticSearch).

        username (optional):
            The username of the specified user whose visible courses we
            want to see. The username is not required only if the API is
            requested by an Anonymous user.

        org (optional):
            If specified, visible `CourseOverview` objects are filtered
            such that only those belonging to the organization with the
            provided org code (e.g., "HarvardX") are returned.
            Case-insensitive.

        permissions (optional):
            If specified, it filters visible `CourseOverview` objects by
            checking if each permission specified is granted for the username.
            Notice that Staff users are always granted permission to list any
            course.

        active_only (optional):
            If this boolean is specified, only the courses that have not ended or do not have any end
            date are returned. This is different from search_term because this filtering is done on
            CourseOverview and not ElasticSearch.

    **Returns**

        * 200 on success, with a list of course discovery objects as returned
          by `CourseDetailView`.
        * 400 if an invalid parameter was sent or the username was not provided
          for an authenticated request.
        * 403 if a user who does not have permission to masquerade as
          another user specifies a username other than their own.
        * 404 if the specified user does not exist, or the requesting user does
          not have permission to view their courses.

        Example response:

            [
              {
                "blocks_url": "/api/courses/v1/blocks/?course_id=edX%2Fexample%2F2012_Fall",
                "media": {
                  "course_image": {
                    "uri": "/c4x/edX/example/asset/just_a_test.jpg",
                    "name": "Course Image"
                  }
                },
                "description": "An example course.",
                "end": "2015-09-19T18:00:00Z",
                "enrollment_end": "2015-07-15T00:00:00Z",
                "enrollment_start": "2015-06-15T00:00:00Z",
                "course_id": "edX/example/2012_Fall",
                "name": "Example Course",
                "number": "example",
                "org": "edX",
                "start": "2015-07-17T12:00:00Z",
                "start_display": "July 17, 2015",
                "start_type": "timestamp"
              }
            ]
    """
    class CourseListPageNumberPagination(LazyPageNumberPagination):
        max_page_size = 500

    pagination_class = CourseListPageNumberPagination
    serializer_class = CourseSerializer
    throttle_classes = (CourseListUserThrottle,)

    def get_queryset(self):
        """
        Yield courses visible to the user.
        """
        form = CourseListGetForm(self.request.query_params, initial={'requesting_user': self.request.user})
        if not form.is_valid():
            raise ValidationError(form.errors)
        return list_courses(
            self.request,
            form.cleaned_data['username'],
            org=form.cleaned_data['org'],
            filter_=form.cleaned_data['filter_'],
            search_term=form.cleaned_data['search_term'],
            permissions=form.cleaned_data['permissions'],
            active_only=form.cleaned_data.get('active_only', False)
        )


class CourseIdListUserThrottle(UserRateThrottle):
    """Limit the number of requests users can make to the course list id API."""

    THROTTLE_RATES = {
        'user': '20/minute',
        'staff': '40/minute',
    }

    def allow_request(self, request, view):
        # Use a special scope for staff to allow for a separate throttle rate
        user = request.user
        if user.is_authenticated and (user.is_staff or user.is_superuser):
            self.scope = 'staff'
            self.rate = self.get_rate()
            self.num_requests, self.duration = self.parse_rate(self.rate)

        return super().allow_request(request, view)


@view_auth_classes()
class CourseIdListView(DeveloperErrorViewMixin, ListAPIView):
    """
    **Use Cases**

        Request a list of course IDs for all courses the specified user can
        access based on the provided parameters.

    **Example Requests**

        GET /api/courses/v1/courses_ids/

    **Response Values**

        Body comprises a list of course ids and pagination details.

    **Parameters**

        username (optional):
            The username of the specified user whose visible courses we
            want to see.

        role (required):
            Course ids are filtered such that only those for which the
            user has the specified role are returned. Role can be "staff"
            or "instructor".
            Case-insensitive.

    **Returns**

        * 200 on success, with a list of course ids and pagination details
        * 400 if an invalid parameter was sent or the username was not provided
          for an authenticated request.
        * 403 if a user who does not have permission to masquerade as
          another user who specifies a username other than their own.
        * 404 if the specified user does not exist, or the requesting user does
          not have permission to view their courses.

        Example response:

            {
                "results":
                    [
                        "course-v1:edX+DemoX+Demo_Course"
                    ],
                "pagination": {
                    "previous": null,
                    "num_pages": 1,
                    "next": null,
                    "count": 1
                }
            }

    """
    class CourseIdListPageNumberPagination(LazyPageNumberPagination):
        max_page_size = 1000

    pagination_class = CourseIdListPageNumberPagination
    serializer_class = CourseKeySerializer
    throttle_classes = (CourseIdListUserThrottle,)

    @function_trace('get_queryset')
    def get_queryset(self):
        """
        Returns CourseKeys for courses which the user has the provided role.
        """
        form = CourseIdListGetForm(self.request.query_params, initial={'requesting_user': self.request.user})
        if not form.is_valid():
            raise ValidationError(form.errors)

        return list_course_keys(
            self.request,
            form.cleaned_data['username'],
            role=form.cleaned_data['role'],
        )

    @function_trace('paginate_queryset')
    def paginate_queryset(self, *args, **kwargs):
        """
        No-op passthrough function purely for function-tracing (monitoring)
        purposes.

        This should be called once per GET request.
        """
        return super().paginate_queryset(*args, **kwargs)

    @function_trace('get_paginated_response')
    def get_paginated_response(self, *args, **kwargs):
        """
        No-op passthrough function purely for function-tracing (monitoring)
        purposes.

        This should be called only when the response is paginated. Two pages
        means two GET requests and one function call per request. Otherwise, if
        the whole response fits in one page, this function never gets called.
        """
        return super().get_paginated_response(*args, **kwargs)

    @function_trace('filter_queryset')
    def filter_queryset(self, *args, **kwargs):
        """
        No-op passthrough function purely for function-tracing (monitoring)
        purposes.

        This should be called once per GET request.
        """
        return super().filter_queryset(*args, **kwargs)

    @function_trace('get_serializer')
    def get_serializer(self, *args, **kwargs):
        """
        No-op passthrough function purely for function-tracing (monitoring)
        purposes.

        This should be called once per GET request.
        """
        return super().get_serializer(*args, **kwargs)


def get_customer_info(user):
    if not user.is_active:
        return {
            'is_superuser': False,
            'is_staff': False,
            'insights_reports': [],
            'details': []
        }
    data = []
    insights_reports = OrganizationType.get_all_insights_reports()
    handler = CourseAccessHandler()
    courses = handler.claim_staff_courses({
        'user': user,
        'values': None
    })
    if courses:
        deactivated_orgs = get_inactive_orgs()
        org_list = []
        for course in courses:
            org = CourseKey.from_string(course).org
            if org not in deactivated_orgs:
                org_list.append(org)

        data = Organization.objects.filter(org__in=org_list).prefetch_related('org_type')
        if data and len(org_list) == len(data):
            insights_reports = set()
            for v in data:
                insights_reports.update(v.get_insights_reports())
            insights_reports = list(insights_reports)
    return {
        'is_superuser': user.is_superuser,
        'is_staff': user.is_staff,
        'insights_reports': insights_reports,
        'details': [v.to_dict() for v in data]
    }


class CourseIdExtendedListView(APIView):
    authentication_classes = (JwtAuthentication, OAuth2AuthenticationAllowInactiveUser)
    permission_classes = ApiKeyHeaderPermissionIsAuthenticated,

    def get(self, request):
        courses = []
        if request.user.is_active:
            handler = CourseAccessHandler()
            courses = handler.claim_staff_courses({
                'user': request.user,
                'values': None
            })
        return Response({'courses': courses})


class OrgsCourseInfoView(APIView):
    authentication_classes = (JwtAuthentication, OAuth2AuthenticationAllowInactiveUser)
    permission_classes = ApiKeyHeaderPermissionIsAuthenticated,

    def post(self, request):
        courses = []

        try:
            json_body = json.loads(request.body.decode('utf8'))
        except ValueError:
            return Response('Invalid JSON body', status=400)

        if not isinstance(json_body, dict):
            return Response('JSON body must be in the dict format', status=400)

        org_list = json_body.get('orgs', [])

        if not org_list or not isinstance(org_list, list):
            return Response({'courses': []})

        course_overviews = CourseOverview.objects.filter(org__in=org_list)

        for course in course_overviews:
            courses.append({
                'id': str(course.id),
                'start_date': course.start_date,
                'end_date': course.end_date
            })

        return Response({'courses': courses})


class CustomerInfoView(APIView):
    authentication_classes = (JwtAuthentication, OAuth2AuthenticationAllowInactiveUser)
    permission_classes = ApiKeyHeaderPermissionIsAuthenticated,

    def get(self, request):
        return Response(get_customer_info(request.user))


class OrgsView(APIView):
    authentication_classes = (JwtAuthentication, OAuth2AuthenticationAllowInactiveUser)
    permission_classes = ApiKeyHeaderPermissionIsAuthenticated,

    def get(self, request):
        org_slug = request.GET.get('org_slug', None)
        org_type = request.GET.get('org_type', None)
        deactivated_orgs = get_inactive_orgs()
        details = {}

        if org_type:
            try:
                org_type = int(org_type)
            except:
                org_type = None

        if org_slug:
            insights_reports = OrganizationType.get_all_insights_reports()
            org_type_result = {}
            if org_slug not in deactivated_orgs:
                try:
                    org_obj = Organization.objects.get(org=org_slug)
                    details = org_obj.to_dict()
                    if org_obj.org_type is not None:
                        insights_reports = org_obj.org_type.get_insights_reports()
                        org_type_result = {
                            'id': org_obj.org_type.id,
                            'title': org_obj.org_type.title
                        }
                except Organization.DoesNotExist:
                    pass
            return Response({
                'success': True,
                'insights_reports': insights_reports,
                'org_type': org_type_result,
                'details': details
            })
        elif org_type:
            orgs = Organization.objects.filter(org_type=org_type).order_by('org')
            return Response({'success': True, 'orgs': [o.org for o in orgs if o.org not in deactivated_orgs]})
        else:
            org_types = OrganizationType.objects.all().order_by('title')
            return Response({'success': True, 'org_types': [{'id': org.id, 'title': org.title} for org in org_types]})


class UpdateCourseStructureView(APIView):
    authentication_classes = (JwtAuthentication, OAuth2AuthenticationAllowInactiveUser)
    permission_classes = ApiKeyHeaderPermissionIsAuthenticated,

    def post(self, request):
        course_id = request.POST.get('course_id')
        if not course_id:
            return Response({'success': False, 'error': "course_id is not set"})

        update_course_structure(course_id)
        return Response({'success': True})


class UpdateSequentialBlockView(APIView):
    authentication_classes = (JwtAuthentication, OAuth2AuthenticationAllowInactiveUser)
    permission_classes = ApiKeyHeaderPermissionIsAuthenticated,

    def post(self, request):
        sequential_id = request.POST.get('sequential_id')
        if not sequential_id:
            return Response({'success': False, 'error': "sequential_id is not set"})

        _update_sequential_block_in_vertica(sequential_id)
        return Response({'success': True})
