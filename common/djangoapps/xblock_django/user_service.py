"""
Support for converting a django user to an XBlock user
"""


from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user
from opaque_keys.edx.keys import CourseKey
from xblock.reference.user_service import UserService, XBlockUser

from openedx.core.djangoapps.external_user_ids.models import ExternalId
from openedx.core.djangoapps.user_api.accounts.utils import is_user_credo_anonymous
from openedx.core.djangoapps.user_api.preferences.api import get_user_preferences
from common.djangoapps.student.models import anonymous_id_for_user, get_user_by_username_or_email, user_by_anonymous_id
from common.djangoapps.student.roles import CourseStaffRole, CourseInstructorRole
from common.djangoapps.credo_modules.models import get_custom_user_role, get_extended_role_default_permissions


from .constants import (
    ATTR_KEY_ANONYMOUS_USER_ID,
    ATTR_KEY_IS_AUTHENTICATED,
    ATTR_KEY_REQUEST_COUNTRY_CODE,
    ATTR_KEY_USER_ID,
    ATTR_KEY_USERNAME,
    ATTR_KEY_USER_IS_STAFF,
    ATTR_KEY_USER_IS_SUPERUSER,
    ATTR_KEY_USER_PREFERENCES,
    ATTR_KEY_USER_ROLE,
    ATTR_KEY_USER_IS_CREDO_ANONYMOUS,
)


USER_PREFERENCES_WHITE_LIST = ['pref-lang', 'time_zone']


class DjangoXBlockUserService(UserService):
    """
    A user service that converts Django users to XBlockUser
    """
    def __init__(self, django_user, **kwargs):
        """
        Constructs a DjangoXBlockUserService object.

        Args:
            user_is_staff(bool): optional - whether the user is staff in the course
            user_role(str): optional -- user's role in the course ('staff', 'instructor', or 'student')
            anonymous_user_id(str): optional - anonymous_user_id for the user in the course
            request_country_code(str): optional -- country code determined from the user's request IP address.
        """
        super().__init__(**kwargs)
        self._django_user = django_user
        if self._django_user:
            self._django_user.user_is_staff = kwargs.get('user_is_staff', False)
        self._user_is_staff = kwargs.get('user_is_staff', False)
        self._user_role = kwargs.get('user_role', 'student')
        self._anonymous_user_id = kwargs.get('anonymous_user_id', None)
        self._request_country_code = kwargs.get('request_country_code', None)

    def get_current_user(self):
        """
        Returns the currently-logged in user, as an instance of XBlockUser
        """
        return self._convert_django_user_to_xblock_user(self._django_user)

    def get_external_user_id(self, type_name):
        """
        Returns an external user id of the given type.
        Raises ValueError if the type doesn't exist.
        """
        external_id, _ = ExternalId.add_new_user_id(self._django_user, type_name)
        if not external_id:
            raise ValueError("External ID type: %s does not exist" % type_name)
        return str(external_id.external_user_id)

    def get_anonymous_user_id(self, username, course_id):
        """
        Get the anonymous user id for a user.

        Args:
            username(str): username of a user.
            course_id(str): course id of particular course.

        Returns:
            A unique anonymous_user_id for (user, course) pair.
            None for Non-staff users.
        """
        if not self.get_current_user().opt_attrs.get(ATTR_KEY_USER_IS_STAFF):
            return None

        try:
            user = get_user_by_username_or_email(username_or_email=username)
        except User.DoesNotExist:
            return None

        course_id = CourseKey.from_string(course_id)
        return anonymous_id_for_user(user=user, course_id=course_id)

    def get_user_by_anonymous_id(self, uid=None):
        """
        Returns the Django User object corresponding to the given anonymous user id.

        Returns None if there is no user with the given anonymous user id.

        If no `uid` is provided, then the current anonymous user ID is used.
        """
        return user_by_anonymous_id(uid or self._anonymous_user_id)

    def is_staff_user(self, course_id):
        if self._django_user:
            return CourseStaffRole(course_id).has_user(self._django_user)
        else:
            return False

    def is_instructor_user(self, course_id):
        if self._django_user:
            return CourseInstructorRole(course_id).has_user(self._django_user)
        else:
            return False

    def is_superadmin_user(self):
        return self._django_user.is_superuser

    def get_user_id(self):
        return self._django_user.id

    def staff_feature_is_available(self, course_id, feature):
        role = get_custom_user_role(course_id, self._django_user, check_enrollment=False)
        if role:
            return getattr(role, feature)
        else:
            default_role = get_extended_role_default_permissions()
            return default_role.get(feature, False)

    def _convert_django_user_to_xblock_user(self, django_user):
        """
        A function that returns an XBlockUser from the current Django request.user
        """
        xblock_user = XBlockUser(is_current_user=True)

        if django_user is not None and django_user.is_authenticated:
            # This full_name is dependent on edx-platform's profile implementation
            if hasattr(django_user, 'profile'):
                full_name = django_user.profile.name
            else:
                full_name = None
            xblock_user.full_name = full_name
            xblock_user.emails = [django_user.email]
            xblock_user.opt_attrs[ATTR_KEY_ANONYMOUS_USER_ID] = self._anonymous_user_id
            xblock_user.opt_attrs[ATTR_KEY_IS_AUTHENTICATED] = True
            xblock_user.opt_attrs[ATTR_KEY_REQUEST_COUNTRY_CODE] = self._request_country_code
            xblock_user.opt_attrs[ATTR_KEY_USER_ID] = django_user.id
            xblock_user.opt_attrs[ATTR_KEY_USERNAME] = django_user.username
            xblock_user.opt_attrs[ATTR_KEY_USER_IS_STAFF] = self._user_is_staff
            xblock_user.opt_attrs[ATTR_KEY_USER_IS_SUPERUSER] = django_user.is_superuser
            xblock_user.opt_attrs[ATTR_KEY_USER_ROLE] = self._user_role
            xblock_user.opt_attrs[ATTR_KEY_USER_IS_CREDO_ANONYMOUS] = is_user_credo_anonymous(django_user)
            user_preferences = get_user_preferences(django_user)
            xblock_user.opt_attrs[ATTR_KEY_USER_PREFERENCES] = {
                pref: user_preferences.get(pref)
                for pref in USER_PREFERENCES_WHITE_LIST
                if pref in user_preferences
            }
        else:
            xblock_user.opt_attrs[ATTR_KEY_IS_AUTHENTICATED] = False
            xblock_user.opt_attrs[ATTR_KEY_REQUEST_COUNTRY_CODE] = self._request_country_code

        return xblock_user
