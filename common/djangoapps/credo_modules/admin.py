import csv
import datetime
from collections import OrderedDict

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.urls import reverse
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils.safestring import mark_safe
from .models import RegistrationPropertiesPerOrg, EnrollmentPropertiesPerCourse,\
    Organization, OrganizationType, CourseExcludeInsights, CustomUserRole, TagDescription, EdxApiToken,\
    RutgersCampusMapping, Feature, FeatureBetaTester, CredoModulesUserProfile, CredoStudentProperties, SendScores,\
    TrackingLogConfig, PropertiesInfo, SiblingBlockUpdateTask, DelayedTask,\
    LoginRedirectAllowedHost, OraBlockScore
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructure, ApiBlockInfoNotSiblings
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers


User = get_user_model()


class RegistrationPropertiesPerOrgForm(admin.ModelAdmin):
    list_display = ('id', 'org')


class EnrollmentPropertiesPerCourseForm(admin.ModelAdmin):
    list_display = ('id', 'course_id')
    search_fields = ('id', 'course_id', 'data')


class OrganizationForm(admin.ModelAdmin):
    search_fields = ('org', 'org_type__title',)
    list_display = ('id', 'org', 'org_type', 'default_frame_domain', 'custom_actions')

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


class OrganizationTypeForm(forms.ModelForm):
    class Meta:
        model = OrganizationType
        fields = '__all__'

    def clean_default_lti_staff_role(self):
        default_lti_staff_role = self.cleaned_data['default_lti_staff_role']
        if default_lti_staff_role:
            av_roles_ids = []
            available_roles = self.cleaned_data['available_roles']
            for av_role in available_roles.all():
                av_roles_ids.append(av_role.id)
            if default_lti_staff_role.id not in av_roles_ids:
                raise ValidationError("Default LTI Staff role must be enabled in Available roles")
        return default_lti_staff_role


class OrganizationTypeAdmin(admin.ModelAdmin):
    list_display = ('id', 'title')
    form = OrganizationTypeForm


class CourseExcludeInsightsForm(forms.ModelForm):
    """ Form for creating custom course entitlement policies. """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].required = False

    class Meta:
        fields = '__all__'
        model = CourseExcludeInsights


class CourseExcludeInsightsAdmin(admin.ModelAdmin):
    list_display = ('id', 'user_id', 'get_username', 'get_email', 'course_id')
    raw_id_fields = ('user',)
    form = CourseExcludeInsightsForm

    def get_actions(self, request):
        actions = super().get_actions(request)
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


class ReadOnlyMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ExportCsvMixin:

    def get_csv_title(self, request, field_name):
        return field_name.replace('_', ' ').upper()

    def get_csv_value(self, request, field_name, obj):
        return getattr(obj, field_name)

    def export_as_csv(self, request):
        queryset = self.get_export_csv_queryset(request)
        now_str = datetime.datetime.now().strftime('%m-%d-%Y_%I_%M_%p')

        field_names = OrderedDict()
        for field_name in self.list_display:
            field_names[field_name] = self.get_csv_title(request, field_name)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename={}_{}.csv'.format(self.csv_name, now_str)
        writer = csv.writer(response)

        writer.writerow(field_names.values())
        for obj in queryset:
            row = []
            for field_name in self.list_display:
                row.append(self.get_csv_value(request, field_name, obj))
            writer.writerow(row)

        return response

    def changelist_view(self, request, extra_context=None):
        if 'action' in request.POST and request.POST['action'] == 'export_as_csv':
            return self.export_as_csv(request)
        return super().changelist_view(request, extra_context)

    export_as_csv.short_description = "Export as CSV"


class DelayedTaskForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'task_id', 'celery_task_id', 'task_name', 'start_time', 'countdown',
                    'attempt_num', 'status', 'result', 'course_id', 'user_id', 'assignment_id', 'created', 'updated')
    search_fields = ['course_id', 'user_id', 'assignment_id']
    ordering = ['-created']


class CredoModulesUserProfileForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'user', 'course_id', 'meta')
    search_fields = ['user__username', 'user__email', 'course_id']


class CredoStudentPropertiesForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'user', 'course_id', 'name', 'value')
    search_fields = ['user__username', 'user__email', 'course_id']


class SendScoresForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'user', 'course_id', 'block_id', 'last_send_time')
    search_fields = ['user__username', 'user__email', 'course_id']


class TrackingLogConfigForm(admin.ModelAdmin):
    list_display = ('key', 'value', 'updated')


class PropertiesInfoForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'org', 'course_id', 'data', 'update_ts')
    search_fields = ['org', 'course_id']


class SiblingBlockUpdateTaskForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'created', 'task_id', 'initiator', 'status',
                    'source_course_id', 'source_block_id', 'sibling_course_id', 'sibling_block_id',
                    'published', 'sibling_block_prev_version')
    search_fields = ['source_course_id', 'source_block_id', 'sibling_course_id', 'sibling_block_id']


class LoginRedirectAllowedHostForm(admin.ModelAdmin):
    list_display = ('id', 'created', 'host', 'is_active')


class ApiBlockInfoNotSiblingsForm(ReadOnlyMixin, admin.ModelAdmin):
    list_filter = [
        "source_course_id",
        "dst_course_id",
    ]
    list_display = ('id', 'source_course_id', 'source_block_id', 'get_source_block_path',
                    'dst_course_id', 'dst_block_id', 'get_dst_block_path', 'created')
    search_fields = ['source_course_id', 'source_block_id', 'dst_course_id', 'dst_block_id']
    ordering = ['source_course_id', 'dst_course_id']

    def get_source_block_path(self, obj):
        block = ApiCourseStructure.objects.filter(block_id=obj.source_block_id).first()
        if block:
            return block.section_path.replace('|', ' > ')

    get_source_block_path.short_description = 'Source Block Path'

    def get_dst_block_path(self, obj):
        block = ApiCourseStructure.objects.filter(block_id=obj.dst_block_id).first()
        if block:
            return block.section_path.replace('|', ' > ')

    get_dst_block_path.short_description = 'Dst Block Path'


class OraBlockScoreForm(admin.ModelAdmin):
    list_display = ('id', 'course_id', 'block_id', 'user',
                    'score_type', 'criterion', 'option_label', 'points_possible', 'points_earned')
    list_select_related = ("user",)
    search_fields = ("course_id", "block_id", "user__id", "user__email", "user__username")


class IgnoredFilter(admin.SimpleListFilter):

    title = 'Display'
    parameter_name = 'display'

    def lookups(self, request, model_admin):
        return (
            (1, 'All'),
            (0, 'Only not ignored'),
        )

    def queryset(self, request, queryset):
        if self.value() is None:
            self.used_parameters[self.parameter_name] = 0
        else:
            self.used_parameters[self.parameter_name] = int(self.value())
        if self.value() == 1:
            return queryset
        return queryset.filter(ignore=False)

    def choices(self, changelist):
        for lookup, title in self.lookup_choices:
            yield {
                'selected': str(self.value()) == str(lookup),
                'query_string': changelist.get_query_string({self.parameter_name: lookup}),
                'display': title,
            }


admin.site.register(RegistrationPropertiesPerOrg, RegistrationPropertiesPerOrgForm)
admin.site.register(EnrollmentPropertiesPerCourse, EnrollmentPropertiesPerCourseForm)
admin.site.register(Organization, OrganizationForm)
admin.site.register(OrganizationType, OrganizationTypeAdmin)
admin.site.register(CourseExcludeInsights, CourseExcludeInsightsAdmin)
admin.site.register(CustomUserRole, CustomUserRoleForm)
admin.site.register(TagDescription, TagDescriptionForm)
admin.site.register(EdxApiToken, EdxApiTokenForm)
admin.site.register(RutgersCampusMapping, RutgersCampusMappingForm)
admin.site.register(Feature, FeatureForm)
admin.site.register(DelayedTask, DelayedTaskForm)
admin.site.register(FeatureBetaTester, FeatureBetaTesterForm)
admin.site.register(CredoModulesUserProfile, CredoModulesUserProfileForm)
admin.site.register(CredoStudentProperties, CredoStudentPropertiesForm)
admin.site.register(SendScores, SendScoresForm)
admin.site.register(TrackingLogConfig, TrackingLogConfigForm)
admin.site.register(PropertiesInfo, PropertiesInfoForm)
admin.site.register(SiblingBlockUpdateTask, SiblingBlockUpdateTaskForm)
admin.site.register(LoginRedirectAllowedHost, LoginRedirectAllowedHostForm)
admin.site.register(ApiBlockInfoNotSiblings, ApiBlockInfoNotSiblingsForm)
admin.site.register(OraBlockScore, OraBlockScoreForm)
