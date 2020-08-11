"""
Course API URLs
"""


from django.conf import settings
from django.conf.urls import include, url

from .views import CourseDetailView, CourseIdListView, CourseListView, CustomerInfoView, OrgsView,\
    UpdateCourseStructureView, CourseIdExtendedListView

urlpatterns = [
    url(r'^v1/courses/$', CourseListView.as_view(), name="course-list"),
    url(r'^v1/courses/{}'.format(settings.COURSE_KEY_PATTERN), CourseDetailView.as_view(), name="course-detail"),
    url(r'^v1/course_ids/$', CourseIdListView.as_view(), name="course-id-list"),
    url(r'^v1/course-ids-extended/$', CourseIdExtendedListView.as_view(), name="course-id-ext-list"),
    url(r'^v1/customer-info/$', CustomerInfoView.as_view(), name="customer-info"),
    url(r'^v1/orgs/$', OrgsView.as_view(), name="orgs-types-info"),
    url(r'^v1/course-structure-update/$', UpdateCourseStructureView.as_view(), name="course-structure-update"),
    url(r'', include('course_api.blocks.urls'))
]
