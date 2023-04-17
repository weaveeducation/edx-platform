from datetime import timedelta
from django.contrib.auth import login
from django.contrib.auth.models import User
from django.conf import settings
from django.utils import timezone
from auth_backends.backends import EdXOAuth2
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


class EdXOpenIdCustomConnent(EdXOAuth2):  # pylint: disable=abstract-method

    def setting(self, name, default=None):
        setting_value = super().setting(name, default)
        if name == 'URL_ROOT' and self.redirect_uri:
            return configuration_helpers.get_value(
                'SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT',
                getattr(settings, 'SOCIAL_AUTH_EDX_OAUTH2_URL_ROOT', settings.LMS_ROOT_URL)
            )
        elif name == 'PUBLIC_URL_ROOT' and self.redirect_uri:
            return configuration_helpers.get_value(
                'SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT',
                getattr(settings, 'SOCIAL_AUTH_EDX_OAUTH2_PUBLIC_URL_ROOT', settings.LMS_ROOT_URL)
            )
        return setting_value


def auto_auth_credo_user(request, user_email):
    if user_email and user_email.endswith('@credomodules.com')\
      and (not request.user.is_authenticated
           or (request.user.email.endswith('@credomodules.com') and request.user.email != user_email)):
        date_joined_limit = timezone.now() - timedelta(days=3)
        edx_user = User.objects.filter(email=user_email, is_active=True, date_joined__gt=date_joined_limit).first()
        if edx_user and not edx_user.is_superuser and not edx_user.is_staff:
            login(request, edx_user, backend=settings.AUTHENTICATION_BACKENDS[0])
            return True
    return False
