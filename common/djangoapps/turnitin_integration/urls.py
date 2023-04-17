from django.conf.urls import url
from .views import turnitin_callback, turnitin_report, turnitin_eula

urlpatterns = [
    url(r'^callback/', turnitin_callback, name='turnitin_callback'),
    url(r'^report/(?P<ora_submission_id>[a-zA-Z0-9\-]+)/(?P<submission_id>\d+)', turnitin_report,
        name='turnitin_report'),
    url(r'^read_eula/(?P<api_key_id>\d+)', turnitin_eula, name='turnitin_eula'),
]
