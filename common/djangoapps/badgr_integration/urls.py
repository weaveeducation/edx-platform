from django.conf.urls import url
from django.conf import settings
from .views import issue_badge, open_badge

urlpatterns = [
    url(
        r'^issue-badge/{course_key}/{usage_key}/'.format(
            course_key=settings.COURSE_ID_PATTERN,
            usage_key=settings.USAGE_ID_PATTERN,
        ),
        issue_badge,
        name="badgr_integration_issue_badge"),
    url(
        r'^open/assertion/(?P<assertion_id>[\w-]+)',
        open_badge,
        name="badgr_integration_open_badge")
]
