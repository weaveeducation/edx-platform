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

    url(r'^tags-global/summary/$',
        views.TagsGlobalSummaryView.as_view(), name='myskills_tags_global_summary'),
    url(r'^tags-global/summary/(?P<student_id>[^/]*)/$',
        views.TagsGlobalSummaryView.as_view(), name='myskills_tags_global_summary_some_user'),

    url(r'^tags-global/all/$',
        views.TagsGlobalView.as_view(), name='myskills_tags_global_all'),
    url(r'^tags-global/all/(?P<student_id>[^/]*)/$',
        views.TagsGlobalView.as_view(), name='myskills_tags_global_all_some_user'),
    url(r'^tags-global/get-tag-data/$',
        views.TagsTagDataView.as_view(), name='myskills_tags_global_tag_data'),
    url(r'^tags-global/get-tag-data/(?P<student_id>[^/]*)/$',
        views.TagsTagDataView.as_view(), name='myskills_tags_global_tag_data_some_user'),
    url(r'^tags-global/get-section-data/$',
        views.TagsTagSectionView.as_view(), name='myskills_tags_global_section_data'),
    url(r'^tags-global/get-section-data/(?P<student_id>[^/]*)/$',
        views.TagsTagSectionView.as_view(), name='myskills_tags_global_section_data_some_user'),

    url(r'^assessments/{}/summary/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentSummaryView.as_view(), name='myskills_assessments_summary'),
    url(r'^assessments/{}/summary/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentSummaryView.as_view(), name='myskills_assessments_summary_some_user'),

    url(r'^assessments/{}/all/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentView.as_view(), name='myskills_assessments_all'),
    url(r'^assessments/{}/all/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.AssessmentView.as_view(), name='myskills_assessments_all_some_user'),

    url(r'^userinfo/{}/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.UserInfo.as_view(), name='myskills_course_user_info_some_user'),
    url(r'^userinfo/(?P<student_id>[^/]*)/$'.format(settings.COURSE_ID_PATTERN),
        views.UserInfo.as_view(), name='myskills_global_user_info_some_user'),
    url(r'^userinfo/$', views.UserInfo.as_view(), name='myskills_global_user_info')
]
