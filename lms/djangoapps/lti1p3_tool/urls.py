from django.conf import settings
from django.conf.urls import url

from .views import login, launch, progress, myskills, launch_deep_link, launch_deep_link_submit, get_jwks

urlpatterns = [
    url(r'^login/?$', login, name="lti1p3_tool_login"),
    url(r'^launch/?$', launch, name="lti1p3_tool_launch"),
    url(r'^launch/myskills/?$', myskills, name="lti1p3_tool_myskills"),
    url(r'^launch/{block_id}/?$'.format(block_id=settings.USAGE_ID_PATTERN),
        launch, name="lti1p3_tool_launch_block"),
    url(r'^launch/course/{course_id}/?$'.format(course_id=settings.COURSE_ID_PATTERN),
        launch_deep_link, name="lti1p3_tool_launch_deep_link"),
    url(r'^launch/course/{course_id}/submit/?$'.format(course_id=settings.COURSE_ID_PATTERN),
        launch_deep_link_submit, name="lti1p3_tool_launch_deep_link_submit"),
    url(r'^launch/course/{course_id}/progress/?$'.format(course_id=settings.COURSE_ID_PATTERN),
        progress, name="lti1p3_tool_launch_progress"),
    url(r'^jwks/(?P<key_id>\d+)/?$', get_jwks, name='lti1p3_tool_get_jwks')
]
