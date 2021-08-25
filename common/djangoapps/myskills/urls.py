from django.conf.urls import url
from django.conf import settings
from common.djangoapps.myskills import views


urlpatterns = [
    url(r'^tags/{}/summary/$'.format(settings.COURSE_ID_PATTERN),
        views.TagsSummaryView.as_view(), name='myskills_tags_summary'),
    url(r'^tags/{}/summary/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.TagsSummaryView.as_view(), name='myskills_tags_summary_some_user'),

    url(r'^tags/{}/all/$'.format(settings.COURSE_ID_PATTERN),
        views.TagsView.as_view(), name='myskills_tags_all'),
    url(r'^tags/{}/all/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.TagsView.as_view(), name='myskills_tags_all_some_user'),

    url(r'^assessments/{}/summary/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentSummaryView.as_view(), name='myskills_assessments_summary'),
    url(r'^assessments/{}/summary/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentSummaryView.as_view(), name='myskills_assessments_summary_some_user'),

    url(r'^assessments/{}/all/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentView.as_view(), name='myskills_assessments_all'),
    url(r'^assessments/{}/all/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentView.as_view(), name='myskills_assessments_all_some_user'),
]
