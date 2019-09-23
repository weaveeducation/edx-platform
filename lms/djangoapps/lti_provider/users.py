"""
LTI user management functionality. This module reconciles the two identities
that an individual has in the campus LMS platform and on edX.
"""

import random
import string
import uuid

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.db import transaction
from django.db.utils import IntegrityError

from lms.djangoapps.utils import _create_edx_user
from lti_provider.models import LtiUser
from student.models import UserProfile
from credo_modules.models import update_unique_user_id_cookie


USERNAME_DB_FIELD_SIZE = 30
FIRST_NAME_DB_FIELD_SIZE = 30
LAST_NAME_DB_FIELD_SIZE = 30
EMAIL_DB_FIELD_SIZE = 254


class UserService(object):

    def get_lti_user_by_external_id(self, lti_user_id, lti_consumer):
        try:
            return LtiUser.objects.get(
                lti_user_id=lti_user_id,
                lti_consumer=lti_consumer
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

    def save_lti_user(self, lti_consumer, lti_user_id, edx_user):
        lti_user = LtiUser(
            lti_consumer=lti_consumer,
            lti_user_id=lti_user_id,
            edx_user=edx_user
        )
        lti_user.save()
        return lti_user

    def _authenticate(self, lti_user, lti_consumer):
        return authenticate(
            username=lti_user.edx_user.username,
            lti_user_id=lti_user.lti_user_id,
            lti_consumer=lti_consumer
        )

    def authenticate_lti_user(self, request, lti_user_id, lti_consumer, lti_params=None):
        """
        Determine whether the user specified by the LTI launch has an existing
        account. If not, create a new Django User model and associate it with an
        LtiUser object.

        If the currently logged-in user does not match the user specified by the LTI
        launch, log out the old user and log in the LTI identity.
        """
        lti_user = self.get_lti_user_by_external_id(lti_user_id, lti_consumer)
        if not lti_user:
            # This is the first time that the user has been here. Create an account.
            lti_user = self.create_lti_user(lti_user_id, lti_consumer, lti_params)

        if not (request.user.is_authenticated and
                request.user == lti_user.edx_user):
            # The user is not authenticated, or is logged in as somebody else.
            # Switch them to the LTI user
            self.switch_user(request, lti_user, lti_consumer)

    def create_lti_user(self, lti_user_id, lti_consumer, lti_params=None):
        """
        Generate a new user on the edX platform with a random username and password,
        and associates that account with the LTI identity.
        """
        if lti_params is None:
            lti_params = {}
        edx_password = str(uuid.uuid4())
        new_user_created = False

        with transaction.atomic():
            if 'email' in lti_params and lti_params['email'].strip():
                lti_params_email = lti_params['email'].strip()
                edx_email = lti_params_email[0:EMAIL_DB_FIELD_SIZE]
                edx_username = lti_params_email.split('@')[0][0:USERNAME_DB_FIELD_SIZE].strip()
                try:
                    edx_user = User.objects.get(email=edx_email)
                    lti_user_found = self.get_lti_user_by_edx_user_id(edx_user.id)
                    if lti_user_found:
                        edx_user = _create_edx_user(edx_user.email, edx_user.username, edx_password, edx_user)
                        new_user_created = True
                except User.DoesNotExist:
                    edx_user = _create_edx_user(edx_email, edx_username, edx_password)
                    new_user_created = True
            else:
                new_username = generate_random_edx_username()
                new_email = "{}@{}".format(new_username, settings.LTI_USER_EMAIL_DOMAIN)
                edx_user = _create_edx_user(new_email, new_username, edx_password)
                new_user_created = True

            if new_user_created and edx_user is not None:
                upd = False
                if 'first_name' in lti_params:
                    edx_user.first_name = cut_to_max_len(lti_params['first_name'].strip(), FIRST_NAME_DB_FIELD_SIZE)
                    upd = True
                if 'last_name' in lti_params:
                    edx_user.last_name = cut_to_max_len(lti_params['last_name'].strip(), LAST_NAME_DB_FIELD_SIZE)
                    upd = True
                if upd:
                    edx_user.save()

                # A profile is required if PREVENT_CONCURRENT_LOGINS flag is set.
                # TODO: We could populate user information from the LTI launch here,
                # but it's not necessary for our current uses.
                edx_user_profile = UserProfile(user=edx_user)
                edx_user_profile.save()

            try:
                with transaction.atomic():
                    lti_user = self.save_lti_user(lti_consumer, lti_user_id, edx_user)
            except IntegrityError:
                lti_user = self.get_lti_user_by_external_id(lti_user_id, lti_consumer)

        return lti_user

    def switch_user(self, request, lti_user, lti_consumer):
        """
        Log out the current user, and log in using the edX identity associated with
        the LTI ID.
        """
        edx_user = self._authenticate(lti_user, lti_consumer)
        if not edx_user:
            # This shouldn't happen, since we've created edX accounts for any LTI
            # users by this point, but just in case we can return a 403.
            raise PermissionDenied()
        login(request, edx_user)
        update_unique_user_id_cookie(request)


def cut_to_max_len(text, max_len):
    """
    Cut a passed string to a max length and return it,
    if the string is less than the max length then it is retured unchanged
    """
    if text is None or len(text) < max_len:
        return text
    else:
        return text[:max_len]


def generate_random_edx_username():
    """
    Create a valid random edX user ID. An ID is at most 30 characters long, and
    can contain upper and lowercase letters and numbers.
    :return:
    """
    allowable_chars = string.ascii_letters + string.digits
    username = ''
    for _index in range(USERNAME_DB_FIELD_SIZE):
        username = username + random.SystemRandom().choice(allowable_chars)
    return username


class LtiBackend(object):
    """
    A Django authentication backend that authenticates users via LTI. This
    backend will only return a User object if it is associated with an LTI
    identity (i.e. the user was created by the create_lti_user method above).
    """

    def authenticate(self, username=None, lti_user_id=None, lti_consumer=None):
        """
        Try to authenticate a user. This method will return a Django user object
        if a user with the corresponding username exists in the database, and
        if a record that links that user with an LTI user_id field exists in
        the LtiUser collection.

        If such a user is not found, the method returns None (in line with the
        authentication backend specification).
        """
        try:
            edx_user = User.objects.get(username=username)
        except User.DoesNotExist:
            return None

        try:
            LtiUser.objects.get(
                edx_user_id=edx_user.id,
                lti_user_id=lti_user_id,
                lti_consumer=lti_consumer
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


def update_lti_user_data(user, lti_email):
    lti_email = lti_email.strip()
    edx_email = lti_email[0:EMAIL_DB_FIELD_SIZE]

    if edx_email and user.email != edx_email:
        edx_username = lti_email.split('@')[0][0:USERNAME_DB_FIELD_SIZE]
        users = User.objects.filter(Q(username=edx_username)|Q(email=edx_email))
        if not users:
            updated = False
            if user.email != edx_email:
                updated = True
                user.email = edx_email
            if user.username != edx_username:
                updated = True
                user.username = edx_username
            if updated:
                user.save()
