from django.apps import AppConfig


class SupervisorEvaluationConfig(AppConfig):
    name = 'lms.djangoapps.supervisor_evaluation'

    def ready(self):
        from lms.djangoapps.supervisor_evaluation import signals  # pylint: disable=unused-import
