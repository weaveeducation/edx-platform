"""
Course API URLs
"""
from django.conf import settings
from django.conf.urls import include, url

from .views import CourseDetailView, CourseListView, CustomerInfoView

urlpatterns = [
    url(r'^v1/courses/$', CourseListView.as_view(), name="course-list"),
    url(r'^v1/courses/{}'.format(settings.COURSE_KEY_PATTERN), CourseDetailView.as_view(), name="course-detail"),
    url(r'^v1/customer-info/$', CustomerInfoView.as_view(), name="customer-info"),
    url(r'', include('course_api.blocks.urls'))
]
