from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from lti_provider.users import UserService
from .models import LtiUser


class Lti1p3UserService(UserService):

    def get_lti_user_by_external_id(self, sub, lti_tool):
        try:
            return LtiUser.objects.get(
                lti_jwt_sub=sub,
                lti_tool=lti_tool
            )
        except LtiUser.DoesNotExist:
            pass
        return None

    def get_lti_user_by_edx_user_id(self, edx_user_id):
        try:
            return LtiUser.objects.get(edx_user_id=edx_user_id)
        except LtiUser.DoesNotExist:
            pass
        return None

    def save_lti_user(self, lti_tool, sub, edx_user):
        lti_user = LtiUser(
            lti_tool=lti_tool,
            lti_jwt_sub=sub,
            edx_user=edx_user
        )
        lti_user.save()
        return lti_user

    def _authenticate(self, lti_user, lti_tool):
        return authenticate(
            username=lti_user.edx_user.username,
            lti_jwt_sub=lti_user.lti_jwt_sub,
            lti_tool=lti_tool
        )


class Lti1p3Backend(object):

    def authenticate(self, username=None, lti_jwt_sub=None, lti_tool=None):
        try:
            edx_user = User.objects.get(username=username)
        except User.DoesNotExist:
            return None

        try:
            LtiUser.objects.get(
                edx_user_id=edx_user.id,
                lti_jwt_sub=lti_jwt_sub,
                lti_tool=lti_tool
            )
        except LtiUser.DoesNotExist:
            return None
        return edx_user

    def get_user(self, user_id):
        """
        Return the User object for a user that has already been authenticated by
        this backend.
        """
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return None
