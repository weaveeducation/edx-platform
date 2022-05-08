""" Handlers for OpenID Connect provider. """

from django.conf import settings
from django.core.cache import cache

from lms.djangoapps.courseware.access import has_access
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from common.djangoapps.student.roles import CourseInstructorRole, CourseStaffRole, GlobalStaff
from common.djangoapps.credo_modules.models import get_inactive_orgs


class CourseAccessHandler:
    """
    Defines two new scopes: `course_instructor` and `course_staff`. Each one is
    valid only if the user is instructor or staff of at least one course.

    Each new scope has a corresponding claim: `instructor_courses` and
    `staff_courses` that lists the course_ids for which the user has instructor
    or staff privileges.

    The claims support claim request values: if there is no claim request, the
    value of the claim is the list all the courses for which the user has the
    corresponding privileges. If a claim request is used, then the value of the
    claim the list of courses from the requested values that have the
    corresponding privileges.

    For example, if the user is staff of course_a and course_b but not
    course_c, the claim corresponding to the scope request:

        scope = openid course_staff

    has the value:

        {staff_courses: [course_a, course_b] }

    For the claim request:

        claims = {userinfo: {staff_courses: {values=[course_b, course_d]}}}

    the corresponding claim will have the value:

        {staff_courses: [course_b] }.

    This is useful to quickly determine if a user has the right privileges for a
    given course.

    For a description of the function naming and arguments, see:

        `edx_oauth2_provider/oidc/handlers.py`

    """

    COURSE_CACHE_TIMEOUT = getattr(settings, 'OIDC_COURSE_HANDLER_CACHE_TIMEOUT', 60)  # In seconds.

    def __init__(self, *_args, **_kwargs):
        self._course_cache = {}

    def scope_course_instructor(self, data):
        """
        Scope `course_instructor` valid only if the user is an instructor
        of at least one course.

        """

        # TODO: unfortunately there is not a faster and still correct way to
        # check if a user is instructor of at least one course other than
        # checking the access type against all known courses.
        course_ids = self.find_courses(data['user'], CourseInstructorRole.ROLE)
        return ['instructor_courses'] if course_ids else None

    def scope_course_staff(self, data):
        """
        Scope `course_staff` valid only if the user is an instructor of at
        least one course.

        """
        # TODO: see :method:CourseAccessHandler.scope_course_instructor
        course_ids = self.find_courses(data['user'], CourseStaffRole.ROLE)

        return ['staff_courses'] if course_ids else None

    def claim_instructor_courses(self, data):
        """
        Claim `instructor_courses` with list of course_ids for which the
        user has instructor privileges.

        """

        return self.find_courses(data['user'], CourseInstructorRole.ROLE, data.get('values'))

    def claim_staff_courses(self, data):
        """
        Claim `staff_courses` with list of course_ids for which the user
        has staff privileges.

        """

        return self.find_courses(data['user'], CourseStaffRole.ROLE, data.get('values'))

    def find_courses(self, user, access_type, values=None):
        """
        Find all courses for which the user has the specified access type. If
        `values` is specified, check only the courses from `values`.

        """

        # Check the instance cache and update if not present.  The instance
        # cache is useful since there are multiple scope and claims calls in the
        # same request.

        key = (user.id, access_type)
        if key in self._course_cache:
            course_ids = self._course_cache[key]
        else:
            course_ids = self._get_courses_with_access_type(user, access_type)
            self._course_cache[key] = course_ids

        # If values was specified, filter out other courses.
        if values is not None:
            course_ids = list(set(course_ids) & set(values))

        deactivated_orgs = get_inactive_orgs()
        if deactivated_orgs:
            new_course_ids = []
            for course_id in course_ids:
                org_ids = course_id.split(':')[1].split('+')[0]
                if org_ids not in deactivated_orgs:
                    new_course_ids.append(course_id)
            return new_course_ids
        else:
            return course_ids

    # pylint: disable=missing-docstring
    def _get_courses_with_access_type(self, user, access_type):
        # Check the application cache and update if not present. The application
        # cache is useful since there are calls to different endpoints in close
        # succession, for example the id_token and user_info endpoints.

        key = '-'.join([str(self.__class__), str(user.id), access_type])
        course_ids = cache.get(key)

        if not course_ids:
            course_keys = CourseOverview.get_all_course_keys()

            # Global staff have access to all courses. Filter courses for non-global staff.
            if not GlobalStaff().has_user(user):
                course_keys = [course_key for course_key in course_keys if has_access(user, access_type, course_key)]

            course_ids = [str(course_key) for course_key in course_keys]

            cache.set(key, course_ids, self.COURSE_CACHE_TIMEOUT)

        return course_ids
