from django.conf.urls import url
from django.conf import settings
from credo_modules import views


urlpatterns = [
    url(r'^profile/{}/$'.format(settings.COURSE_ID_PATTERN),
        views.StudentProfileView.as_view(), name='credo_modules_profile'),
    url(r'^login_as_user/$', views.login_as_user, name='login_as_user')
]
