"""
Admin view for courseware.
"""


from config_models.admin import ConfigurationModelAdmin, KeyedConfigurationModelAdmin
from django.contrib import admin

from lms.djangoapps.courseware import models


class StudentModuleForm(admin.ModelAdmin):
    list_display = ('id', 'course_id', 'module_state_key', 'module_type', 'student', 'grade', 'max_grade',
                    'created', 'modified')
    list_select_related = ("student",)
    search_fields = ("module_state_key", "course_id", "student__id", "student__email", "student__username")


admin.site.register(models.FinancialAssistanceConfiguration, ConfigurationModelAdmin)
admin.site.register(models.DynamicUpgradeDeadlineConfiguration, ConfigurationModelAdmin)
admin.site.register(models.OfflineComputedGrade)
admin.site.register(models.OfflineComputedGradeLog)
admin.site.register(models.CourseDynamicUpgradeDeadlineConfiguration, KeyedConfigurationModelAdmin)
admin.site.register(models.OrgDynamicUpgradeDeadlineConfiguration, KeyedConfigurationModelAdmin)
admin.site.register(models.StudentModule, StudentModuleForm)
