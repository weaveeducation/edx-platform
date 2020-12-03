from django.contrib import admin
from django.urls import reverse
from django import forms
from django.conf import settings
from django.utils.safestring import mark_safe
from .models import RegistrationPropertiesPerOrg, EnrollmentPropertiesPerCourse,\
    Organization, OrganizationType, CourseExcludeInsights, CustomUserRole, TagDescription, EdxApiToken,\
    RutgersCampusMapping, Feature, FeatureBetaTester
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


class RegistrationPropertiesPerOrgForm(admin.ModelAdmin):
    list_display = ('id', 'org')


class EnrollmentPropertiesPerCourseForm(admin.ModelAdmin):
    list_display = ('id', 'course_id')


class OrganizationForm(admin.ModelAdmin):
    search_fields = ('org', 'org_type__title',)
    list_display = ('id', 'org', 'org_type', 'default_frame_domain', 'custom_actions')
    actions = ['actions', ]

    def custom_actions(self, obj):
        cms_base = configuration_helpers.get_value(
            'CMS_BASE',
            getattr(settings, 'CMS_BASE', 'localhost')
        )
        if settings.DEBUG:
            cms_base = 'http://' + cms_base
        else:
            cms_base = 'https://' + cms_base
        return mark_safe('<a href="' + cms_base + reverse('admin-manage-org-tags', kwargs={
            "org_id": obj.id
        }) + '" target="blank">Configure Tags</a> | <a href="'\
               + cms_base + reverse('admin-manage-org-tags-order', kwargs={
                   "org_id": obj.id
               }) + '" target="blank">Set Tags Order</a>')

    custom_actions.short_description = 'Actions'


class OrganizationTypeForm(admin.ModelAdmin):
    list_display = ('id', 'title')


class CourseExcludeInsightsForm(forms.ModelForm):
    """ Form for creating custom course entitlement policies. """
    def __init__(self, *args, **kwargs):
        super(CourseExcludeInsightsForm, self).__init__(*args, **kwargs)
        self.fields['user'].required = False

    class Meta:
        fields = '__all__'
        model = CourseExcludeInsights


class CourseExcludeInsightsAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_id', 'get_username', 'get_email', 'course_id')
    raw_id_fields = ('user',)
    form = CourseExcludeInsightsForm

    def get_actions(self, request):
        actions = super(CourseExcludeInsightsAdmin, self).get_actions(request)
        actions['delete_selected'][0].short_description = "Delete Selected"
        return actions

    def get_username(self, obj):
        if obj.user:
            return obj.user.username
        else:
            return '-'

    def get_email(self, obj):
        if obj.user:
            return obj.user.email
        else:
            return '-'


class CustomUserRoleForm(admin.ModelAdmin):
    list_display = ('id', 'title')


class TagDescriptionForm(admin.ModelAdmin):
    list_display = ('id', 'tag_name', 'description')


class EdxApiTokenForm(admin.ModelAdmin):
    list_display = ('id', 'title', 'is_active')


class RutgersCampusMappingForm(admin.ModelAdmin):
    list_display = ('id', 'num', 'school', 'campus')


class FeatureForm(admin.ModelAdmin):
    list_display = ('id', 'feature_name', 'status')


class FeatureBetaTesterForm(admin.ModelAdmin):
    list_display = ('id', 'feature', 'user')
    raw_id_fields = ('user',)


admin.site.register(RegistrationPropertiesPerOrg, RegistrationPropertiesPerOrgForm)
admin.site.register(EnrollmentPropertiesPerCourse, EnrollmentPropertiesPerCourseForm)
admin.site.register(Organization, OrganizationForm)
admin.site.register(OrganizationType, OrganizationTypeForm)
admin.site.register(CourseExcludeInsights, CourseExcludeInsightsAdmin)
admin.site.register(CustomUserRole, CustomUserRoleForm)
admin.site.register(TagDescription, TagDescriptionForm)
admin.site.register(EdxApiToken, EdxApiTokenForm)
admin.site.register(RutgersCampusMapping, RutgersCampusMappingForm)
admin.site.register(Feature, FeatureForm)
admin.site.register(FeatureBetaTester, FeatureBetaTesterForm)
