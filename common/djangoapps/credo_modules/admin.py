from django.contrib import admin
from .models import RegistrationPropertiesPerMicrosite, EnrollmentPropertiesPerCourse,\
    Organization, OrganizationType, CourseExcludeInsights


class RegistrationPropertiesPerMicrositeForm(admin.ModelAdmin):
    list_display = ('id', 'org', 'domain')


class EnrollmentPropertiesPerCourseForm(admin.ModelAdmin):
    list_display = ('id', 'course_id')


class OrganizationForm(admin.ModelAdmin):
    list_display = ('id', 'org', 'org_type')

    # @TODO Remove fields below after deploy production
    exclude = ('is_courseware_customer', 'is_skill_customer', 'is_modules_customer')


class OrganizationTypeForm(admin.ModelAdmin):
    list_display = ('id', 'title')


class CourseExcludeInsightsForm(admin.ModelAdmin):
    list_display = ('id', 'course_id')

    def get_actions(self, request):
        actions = super(CourseExcludeInsightsForm, self).get_actions(request)
        actions['delete_selected'][0].short_description = "Delete Selected"
        return actions


admin.site.register(RegistrationPropertiesPerMicrosite, RegistrationPropertiesPerMicrositeForm)
admin.site.register(EnrollmentPropertiesPerCourse, EnrollmentPropertiesPerCourseForm)
admin.site.register(Organization, OrganizationForm)
#@TODO uncomment this
#admin.site.register(OrganizationType, OrganizationTypeForm)
admin.site.register(CourseExcludeInsights, CourseExcludeInsightsForm)
