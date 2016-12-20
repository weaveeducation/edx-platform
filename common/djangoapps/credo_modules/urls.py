from django.conf.urls import patterns, url
from django.conf import settings
from credo_modules import views


urlpatterns = patterns(
    '',
    url(r'^profile/{}/$'.format(settings.COURSE_ID_PATTERN),
        views.StudentProfileView.as_view(), name='credo_modules_profile'),
)
