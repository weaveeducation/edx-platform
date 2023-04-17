"""
Course API URLs
"""


from django.conf import settings
from django.urls import include, path, re_path

from .views import CourseDetailView, CourseIdListView, CourseListView, CustomerInfoView, OrgsView,\
    UpdateCourseStructureView, UpdateSequentialBlockView, CourseIdExtendedListView, OrgsCourseInfoView

urlpatterns = [
    path('v1/courses/', CourseListView.as_view(), name="course-list"),
    re_path(fr'^v1/courses/{settings.COURSE_KEY_PATTERN}', CourseDetailView.as_view(), name="course-detail"),
    path('v1/course_ids/', CourseIdListView.as_view(), name="course-id-list"),
    path('v1/course-ids-extended/', CourseIdExtendedListView.as_view(), name="course-id-ext-list"),
    path('v1/customer-info/', CustomerInfoView.as_view(), name="customer-info"),
    path('v1/orgs/', OrgsView.as_view(), name="orgs-types-info"),
    path('v1/orgs/course-info/', OrgsCourseInfoView.as_view(), name="orgs-course-info"),
    path('v1/course-structure-update/', UpdateCourseStructureView.as_view(), name="course-structure-update"),
    path('v1/sequential-block-update/', UpdateSequentialBlockView.as_view(), name="sequential-block-update"),
    path('', include('lms.djangoapps.course_api.blocks.urls')),
]
