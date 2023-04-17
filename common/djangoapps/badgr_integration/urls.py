from django.conf.urls import url
from django.conf import settings
from .views import open_badge, BadgesView, BadgesIssueView, CoursesView

urlpatterns = [
    url(
        r'^issue-badge/{course_key}/{usage_key}/'.format(
            course_key=settings.COURSE_ID_PATTERN,
            usage_key=settings.USAGE_ID_PATTERN,
        ),
        BadgesIssueView.as_view(),
        name="badgr_integration_issue_badge"),
    url(
        r'^open/assertion/(?P<assertion_id>[\w-]+)',
        open_badge,
        name="badgr_integration_open_badge"),
    url(
        r'^api/{}/assertions/$'.format(settings.COURSE_ID_PATTERN),
        BadgesView.as_view(),
        name='badgr_integration_api_badges'),
    url(
        r'^api/courses/$',
        CoursesView.as_view(),
        name='badgr_integration_api_courses'),
]
