from django.contrib import admin
from .models import RegistrationPropertiesPerMicrosite, EnrollmentPropertiesPerCourse, Organization,\
    CourseExcludeInsights


class RegistrationPropertiesPerMicrositeForm(admin.ModelAdmin):
    list_display = ('id', 'org', 'domain')


class EnrollmentPropertiesPerCourseForm(admin.ModelAdmin):
    list_display = ('id', 'course_id')


class OrganizationForm(admin.ModelAdmin):
    list_display = ('id', 'org')


class CourseExcludeInsightsForm(admin.ModelAdmin):
    list_display = ('id', 'course_id')

    def get_actions(self, request):
        actions = super(CourseExcludeInsightsForm, self).get_actions(request)
        actions['delete_selected'][0].short_description = "Delete Selected"
        return actions


admin.site.register(RegistrationPropertiesPerMicrosite, RegistrationPropertiesPerMicrositeForm)
admin.site.register(EnrollmentPropertiesPerCourse, EnrollmentPropertiesPerCourseForm)
admin.site.register(Organization, OrganizationForm)
admin.site.register(CourseExcludeInsights, CourseExcludeInsightsForm)
