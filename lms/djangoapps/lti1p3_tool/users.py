from django.db import IntegrityError, transaction
from django.contrib.auth import authenticate
from django.contrib.auth import get_user_model
from lms.djangoapps.lti_provider.users import UserService
from .models import LtiUser, LtiUserEnrollment


User = get_user_model()


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

    def _authenticate(self, request, lti_user, lti_tool):
        return authenticate(
            request=request,
            username=lti_user.edx_user.username,
            lti_jwt_sub=lti_user.lti_jwt_sub,
            lti_tool=lti_tool
        )

    def update_external_enrollment(self, lti_user, external_course, context_label, context_title):
        ext_enrollment = LtiUserEnrollment.objects.filter(
            lti_user=lti_user, external_course=external_course).first()

        properties = {
            'context_label': context_label,
            'context_title': context_title
        }

        if not ext_enrollment:
            try:
                with transaction.atomic():
                    ext_enrollment = LtiUserEnrollment(
                        lti_user=lti_user,
                        external_course=external_course,
                    )
                    ext_enrollment.set_properties(properties)
                    ext_enrollment.save()
            except IntegrityError:
                pass


class Lti1p3Backend(object):

    def authenticate(self, _request, username=None, lti_jwt_sub=None, lti_tool=None):
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
