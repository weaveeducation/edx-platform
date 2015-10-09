import os
from path import path
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.files.storage import FileSystemStorage
from django.contrib.staticfiles.finders import BaseFinder
from django.contrib.staticfiles import utils


class ComprehensiveThemeFinder(BaseFinder):
    """
    A static files finder that searches the active comprehensive theme
    for locate files. If the ``COMP_THEME_DIR`` setting is unset, or the
    ``COMP_THEME_DIR`` does not exist on the file system, this finder will
    never find any files.
    """
    def __init__(self, *args, **kwargs):
        COMP_THEME_DIR = getattr(settings, "COMP_THEME_DIR", "")
        if not COMP_THEME_DIR:
            self.storage = None
            return

        if not isinstance(settings.COMP_THEME_DIR, basestring):
            raise ImproperlyConfigured("Your COMP_THEME_DIR setting must be a string")

        PROJECT_ROOT = getattr(settings, "PROJECT_ROOT", "")
        if PROJECT_ROOT.endswith("cms"):
            THEME_STATIC_DIR = path(settings.COMP_THEME_DIR) / "studio" / "static"
        else:
            THEME_STATIC_DIR = path(settings.COMP_THEME_DIR) / "lms" / "static"

        self.storage = FileSystemStorage(location=THEME_STATIC_DIR)

        super(ComprehensiveThemeFinder, self).__init__(*args, **kwargs)

    def find(self, path, all=False):
        """
        Looks for files in the default file storage, if it's local.
        """
        if not self.storage:
            return []

        if self.storage.exists(path):
            match = self.storage.path(path)
            if all:
                match = [match]
            return match

        return []

    def list(self, ignore_patterns):
        """
        List all files of the storage.
        """
        if self.storage and self.storage.exists(''):
            for path in utils.get_files(self.storage, ignore_patterns):
                yield path, self.storage
