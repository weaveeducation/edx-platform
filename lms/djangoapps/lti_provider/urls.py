"""
LTI Provider API endpoint urls.
"""

from django.conf import settings
from django.conf.urls import patterns, url

urlpatterns = patterns(
    '',

    url(
        r'^courses/{course_id}/{usage_id}$'.format(
            course_id=settings.COURSE_ID_PATTERN,
            usage_id=settings.USAGE_ID_PATTERN
        ),
        'lti_provider.views.lti_launch', name="lti_provider_launch"),
    url(
        r'^courses/{course_id}/{usage_id}/new_tab/?$'.format(
            course_id=settings.COURSE_ID_PATTERN,
            usage_id=settings.USAGE_ID_PATTERN
        ),
        'lti_provider.views.lti_launch_new_tab', name="lti_launch_new_tab"),
    url(
        r'^test/?$', 'lti_provider.views.test_launch', name="lti_provider_test_launch"),
)
