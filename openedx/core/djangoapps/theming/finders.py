import os
from path import path
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from staticfiles.finders import BaseFinder


class ComprehensiveThemeFinder(BaseFinder):
    """
    A static files finder that searches the active comprehensive theme
    for locate files. If the ``COMP_THEME_DIR`` setting is unset, or the
    ``COMP_THEME_DIR`` does not exist on the file system, this finder will
    never find any files.
    """
    def __init__(self, apps=None, *args, **kwargs):
        if not getattr(settings, "COMP_THEME_DIR", None):
            self.THEME_STATIC_DIR = None
        if not isinstance(settings.COMP_THEME_DIR, basestring):
            raise ImproperlyConfigured("Your COMP_THEME_DIR setting must be a string")
        PROJECT_ROOT = getattr(settings, "PROJECT_ROOT", "")
        if PROJECT_ROOT.endswith("cms"):
            self.THEME_STATIC_DIR = path(settings.COMP_THEME_DIR) / "studio" / "static"
        else:
            self.THEME_STATIC_DIR = path(settings.COMP_THEME_DIR) / "lms" / "static"

    def find(self, path, all=False):
        if not self.THEME_STATIC_DIR or not self.THEME_STATIC_DIR.exists():
            return None

        to_check = self.THEME_STATIC_DIR / path
        if to_check.exists():
            return to_check
