from django.conf.urls import url
from django.conf import settings
from .views import render_supervisor_evaluation_block, generate_pdf_report,\
    SurveyResults, ReportsView, CoursesView, SupervisorEvaluationProfileView

urlpatterns = [
    url(r'^evaluation/(?P<hash_id>[\w-]+)', render_supervisor_evaluation_block,
        name="supervisor_evaluation_block"),
    url(r'^profile/(?P<hash_id>[\w-]+)/$', SupervisorEvaluationProfileView.as_view(),
        name='supervisor_evaluation_profile'),
    url(r'^api/results/(?P<hash_id>[\w-]+)/$', SurveyResults.as_view(),
        name='supervisor_api_survey_results'),
    url(r'^api/{}/reports/$'.format(settings.COURSE_ID_PATTERN), ReportsView.as_view(),
        name='supervisor_api_reports'),
    url(r'^api/courses/$', CoursesView.as_view(),
        name='supervisor_api_courses'),
    url(r'^generate-pdf-report/(?P<hash_id>[\w-]+)', generate_pdf_report,
        name="supervisor_generate_pdf_report")
]
