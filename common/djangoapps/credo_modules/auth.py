from django.conf import settings
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
