"""
Helper Methods
"""

from django.contrib.auth.models import User
from django.db.models import Q
from django.db import transaction
from django.db.utils import IntegrityError

USERNAME_DB_FIELD_SIZE = 30
EMAIL_DB_FIELD_SIZE = 254


def _get_key(key_or_id, key_cls):
    """
    Helper method to get a course/usage key either from a string or a key_cls,
    where the key_cls (CourseKey or UsageKey) will simply be returned.
    """
    return (
        key_cls.from_string(key_or_id)
        if isinstance(key_or_id, basestring)
        else key_or_id
    )


def _create_edx_user(email, username, password, user=None):
    i = 1
    new_email = email
    new_username = username

    if user is not None:
        new_email, new_username = _get_new_email_and_username(user, new_email, new_username, i)
        i = i + 1

    while True:
        try:
            with transaction.atomic():
                return User.objects.create_user(
                    email=new_email,
                    username=new_username,
                    password=password
                )
        except IntegrityError:
            ex_user = User.objects.get(Q(email=new_email) | Q(username=new_username))
            new_email, new_username = _get_new_email_and_username(ex_user, new_email, new_username, i)
            i = i + 1


def _get_new_email_and_username(ex_user, new_email, new_username, num):
    if ex_user.email == new_email:
        if len(ex_user.email) > (EMAIL_DB_FIELD_SIZE - 3):
            new_email = ex_user.email[0:EMAIL_DB_FIELD_SIZE - 3] + str(num)
        else:
            new_email = ex_user.email + str(num)
    if ex_user.username.lower() == new_username.lower():
        if len(ex_user.username) > (USERNAME_DB_FIELD_SIZE - 3):
            new_username = new_username[0:USERNAME_DB_FIELD_SIZE - 3] + str(num)
        else:
            new_username = new_username + str(num)

    return new_email, new_username
