"""
Base class for pages in courseware.
"""

from bok_choy.page_object import PageObject
from bok_choy.promise import EmptyPromise
from . import BASE_URL
from .tab_nav import TabNavPage


class CoursePage(PageObject):
    """
    Abstract base class for page objects within a course.
    """

    # Overridden by subclasses to provide the relative path within the course
    # Paths should not include the leading forward slash.
    url_path = ""

    def __init__(self, browser, course_id):
        """
        Course ID is currently of the form "edx/999/2013_Spring"
        but this format could change.
        """
        super(CoursePage, self).__init__(browser)
        self.course_id = course_id

    @property
    def url(self):
        """
        Construct a URL to the page within the course.
        """
        return BASE_URL + "/courses/" + self.course_id + "/" + self.url_path

    def has_tab(self, tab_name):
        """
        Returns true if the current page is showing a tab with the given name.
        :return:
        """
        tab_nav = TabNavPage(self.browser)
        return tab_name in tab_nav.tab_names

    def skip_to_main_content(self):
        """
        Ensures skip links function and focus on the intended href
        """

        skip_to = self.q(css=".nav-skip").attrs('href')[0]
        self.q(css=".nav-skip").first().click()
        return EmptyPromise(
            lambda: self.q(skip_to).present, "Main content area received focus"
        ).fullfill()
