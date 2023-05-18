"""
Django admin page for grades models
"""


from config_models.admin import ConfigurationModelAdmin
from django.contrib import admin

from lms.djangoapps.grades.config.models import (
    ComputeGradesSetting
)
from lms.djangoapps.grades.models import PersistentCourseGrade, PersistentSubsectionGrade


class PersistentCourseGradeAdmin(admin.ModelAdmin):
    list_display = ("id", "course_id", "user_id", "course_version", "percent_grade", "letter_grade", "passed_timestamp")
    search_fields = ("user_id", "course_id",)


class PersistentSubsectionGradeAdmin(admin.ModelAdmin):
    list_display = ("id", "course_id", "usage_key", "user_id", "course_version", "earned_all", "possible_all",
                    "earned_graded", "possible_graded", "first_attempted", "last_attempted")
    search_fields = ("user_id", "course_id", "usage_key")


admin.site.register(ComputeGradesSetting, ConfigurationModelAdmin)
admin.site.register(PersistentCourseGrade, PersistentCourseGradeAdmin)
admin.site.register(PersistentSubsectionGrade, PersistentSubsectionGradeAdmin)
