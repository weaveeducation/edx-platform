import os
from path import path
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.contrib.staticfiles.finders import BaseStorageFinder
try:
    from staticfiles.finders import BaseFinder
except ImportError:
    BaseFinder = object


class ComprehensiveThemeFinder(BaseStorageFinder, BaseFinder):
    """
    A static files finder that searches the active comprehensive theme
    for locate files. If the ``COMP_THEME_DIR`` setting is unset, or the
    ``COMP_THEME_DIR`` does not exist on the file system, this finder will
    never find any files.
    """
    def __init__(self, *args, **kwargs):
        COMP_THEME_DIR = getattr(settings, "COMP_THEME_DIR", "")
        if not isinstance(settings.COMP_THEME_DIR, basestring):
            raise ImproperlyConfigured("Your COMP_THEME_DIR setting must be a string")

        PROJECT_ROOT = getattr(settings, "PROJECT_ROOT", "")
        if PROJECT_ROOT.endswith("cms"):
            THEME_STATIC_DIR = path(settings.COMP_THEME_DIR) / "studio" / "static"
        else:
            THEME_STATIC_DIR = path(settings.COMP_THEME_DIR) / "lms" / "static"

        self.storage = FileSystemStorage(location=THEME_STATIC_DIR)

        super(ComprehensiveThemeFinder, self).__init__(*args, **kwargs)
