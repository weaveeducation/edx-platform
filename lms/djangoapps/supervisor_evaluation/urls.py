from django.conf.urls import url
from .views import render_supervisor_evaluation_block, SurveyResults, SupervisorEvaluationProfileView

urlpatterns = [
    url(r'^evaluation/(?P<hash_id>[\w-]+)', render_supervisor_evaluation_block,
        name="supervisor_evaluation_block"),
    url(r'^profile/(?P<hash_id>[\w-]+)/$', SupervisorEvaluationProfileView.as_view(),
        name='supervisor_evaluation_profile'),
    url(r'^api/results/(?P<hash_id>[\w-]+)/$', SurveyResults.as_view(),
        name='supervisor_api_survey_results')
]
