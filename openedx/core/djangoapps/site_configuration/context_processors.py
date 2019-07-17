"""
Django template context processors.
"""

from django.conf import settings
from django.utils.http import urlquote_plus

from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


def configuration_context(request):  # pylint: disable=unused-argument
    """
    Configuration context for django templates.
    """
    return {
        'platform_name': configuration_helpers.get_value('platform_name', settings.PLATFORM_NAME),
        'current_url': urlquote_plus(request.build_absolute_uri(request.path)),
        'current_site_url': urlquote_plus(request.build_absolute_uri('/')),
        'lms_root_url': configuration_helpers.get_value('LMS_ROOT_URL', settings.LMS_ROOT_URL),
        'lms_base': configuration_helpers.get_value('LMS_BASE', getattr(settings, 'LMS_BASE', ''))
    }
