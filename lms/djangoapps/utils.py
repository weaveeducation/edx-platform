"""
Helper Methods
"""

from braze.client import BrazeClient
from django.conf import settings
from optimizely import optimizely
from optimizely.config_manager import PollingConfigManager
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.db import transaction
from django.db.utils import IntegrityError

User = get_user_model()
USERNAME_DB_FIELD_SIZE = 30
EMAIL_DB_FIELD_SIZE = 254


def _get_key(key_or_id, key_cls):
    """
    Helper method to get a course/usage key either from a string or a key_cls,
    where the key_cls (CourseKey or UsageKey) will simply be returned.
    """
    return (
        key_cls.from_string(key_or_id)
        if isinstance(key_or_id, str)
        else key_or_id
    )


def get_braze_client():
    """ Returns a Braze client. """
    braze_api_key = settings.EDX_BRAZE_API_KEY
    braze_api_url = settings.EDX_BRAZE_API_SERVER

    if not braze_api_key or not braze_api_url:
        return None

    return BrazeClient(
        api_key=braze_api_key,
        api_url=braze_api_url,
        app_id='',
    )


class OptimizelyClient:
    """ Class for instantiating an Optimizely full stack client instance. """
    optimizely_client = None

    @classmethod
    def get_optimizely_client(cls):
        if not cls.optimizely_client:
            optimizely_sdk_key = settings.OPTIMIZELY_FULLSTACK_SDK_KEY
            if not optimizely_sdk_key:
                return None

            config_manager = PollingConfigManager(
                update_interval=10,
                sdk_key=optimizely_sdk_key,
            )
            cls.optimizely_client = optimizely.Optimizely(config_manager=config_manager)

        return cls.optimizely_client


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
