"""
Base Message types to be used to construct ace messages.
"""

from django.conf import settings
from edx_ace.message import MessageType

from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


class BaseMessageType(MessageType):  # lint-amnesty, pylint: disable=missing-class-docstring
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from_address = configuration_helpers.get_value('email_from_address')
        if from_address:
            self.options.update({'from_address': from_address})  # pylint: disable=no-member
        if settings.OUTPUT_FILE_PATH:
            self.options.update({'output_file_path': settings.OUTPUT_FILE_PATH})

