"""
LTI Provider API endpoint urls.
"""

from django.conf import settings
from django.conf.urls import url

from lti_provider import views

urlpatterns = [
    url(
        r'^courses/{course_id}/progress$'.format(
            course_id=settings.COURSE_ID_PATTERN,
        ),
        views.lti_progress, name="lti_provider_progress"),
    url(
        r'^courses/{course_id}/{usage_id}$'.format(
            course_id=settings.COURSE_ID_PATTERN,
            usage_id=settings.USAGE_ID_PATTERN
        ),
        views.lti_launch, name="lti_provider_launch"),
    url(r'^test/?$', views.test_launch, name="lti_provider_test_launch"),
]
