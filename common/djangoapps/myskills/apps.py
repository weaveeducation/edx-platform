from django.apps import AppConfig


class MySkillsAppConfig(AppConfig):
    name = 'common.djangoapps.myskills'
    verbose_name = 'MySkills'

    def ready(self):
        from common.djangoapps.myskills import handlers
