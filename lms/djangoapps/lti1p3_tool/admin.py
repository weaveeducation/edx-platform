import json

from django.contrib import admin, messages
from django.conf import settings
from django.urls import reverse
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers
from .models import (
    LtiTool,
    LtiToolKey,
    LtiExternalCourse,
    LtiUserEnrollment,
    LtiPlatform,
    LtiDeepLink,
    LtiDeepLinkCourse
)
from .tasks import lti1p3_sync_course_enrollments


class ReadOnlyMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class LtiToolKeyAdmin(admin.ModelAdmin):
    """Admin for LTI Tool Key"""
    list_display = ('id', 'name')

    add_fieldsets = (
        (None, {'fields': ('name',)}),
    )

    change_fieldsets = (
        (None, {'fields': ('name', 'private_key_hidden', 'public_key', 'public_key_jwk_json')}),
    )

    readonly_fields = ('private_key_hidden', 'public_key', 'public_key_jwk_json')

    def get_form(self, request, obj=None, **kwargs):
        help_texts = {'public_key_jwk_json': "Tool's generated Public key presented as JWK. "
                                             "Provide this value to Platforms"}
        kwargs.update({'help_texts': help_texts})
        return super().get_form(request, obj, **kwargs)

    def get_fieldsets(self, request, obj=None):
        if not obj:
            return self.add_fieldsets
        else:
            return self.change_fieldsets

    def private_key_hidden(self, obj):
        return '<hidden>'

    private_key_hidden.short_description = 'Private key'

    def public_key_jwk_json(self, obj):
        return json.dumps(obj.public_jwk)

    public_key_jwk_json.short_description = "Public key in JWK format"


class LtiToolAdmin(admin.ModelAdmin):
    """Admin for LTI Tool"""
    search_fields = ('title', 'issuer', 'client_id', 'auth_login_url', 'auth_token_url', 'key_set_url')
    list_display = ('id', 'title', 'is_active', 'issuer', 'client_id', 'deployment_ids', 'force_create_lineitem')


class LtiPlatformAdmin(admin.ModelAdmin):
    search_fields = ('title',)
    list_display = ('id', 'title')


class LtiExternalCourseAdmin(ReadOnlyMixin, admin.ModelAdmin):
    search_fields = ('external_course_id', 'edx_course_id', 'lti_tool__title',)
    list_display = ('id', 'external_course_id', 'edx_course_id', 'lti_tool', 'context_memberships_url',
                    'users_last_sync_date')
    list_select_related = ("lti_tool",)

    actions = ['sync_course_enrollments', ]

    def sync_course_enrollments(self, request, queryset):
        for item in queryset:
            lti1p3_sync_course_enrollments.delay(item.pk)
        messages.info(request, f'Sync tasks for the selected courses were added into queue')

    sync_course_enrollments.short_description = 'Sync Enrollments using LTI 1.3 NRPS'


class LtiUserEnrollmentAdmin(ReadOnlyMixin, admin.ModelAdmin):
    search_fields = (
        'external_course__external_course_id',
        'external_course__edx_course_id',
        'lti_user__lti_jwt_sub',
    )
    list_display = ('id', 'get_external_course', 'get_edx_course', 'get_lti_user_external_id',
                    'get_lti_user_edx', 'get_lti_tool',  'properties', 'created')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'lti_user', 'lti_user__edx_user', 'external_course', 'external_course__lti_tool')

    def get_external_course(self, obj):
        return obj.external_course.external_course_id

    get_external_course.short_description = 'External Course'

    def get_edx_course(self, obj):
        return obj.external_course.edx_course_id

    get_edx_course.short_description = 'Edx Course'

    def get_lti_user_external_id(self, obj):
        return obj.lti_user.lti_jwt_sub

    get_lti_user_external_id.short_description = 'User External Id'

    def get_lti_user_edx(self, obj):
        return obj.lti_user.edx_user.email

    get_lti_user_edx.short_description = 'Edx User'

    def get_lti_tool(self, obj):
        return obj.external_course.lti_tool

    get_lti_tool.short_description = 'LTI tool'


class LtiDeepLinkCourseInline(admin.TabularInline):
    model = LtiDeepLinkCourse
    extra = 0


class LtiDeepLinkAdmin(admin.ModelAdmin):
    search_fields = ('title', 'url_token', 'lti_tool__title',)
    list_display = ('id', 'title', 'lti_dl_url', 'url_token', 'lti_tool', 'is_active')
    list_select_related = ("lti_tool",)
    inlines = (LtiDeepLinkCourseInline,)

    def lti_dl_url(self, obj):
        lms_base = configuration_helpers.get_value(
            'LMS_BASE',
            getattr(settings, 'LMS_BASE', 'localhost')
        )
        if settings.DEBUG:
            lms_base = 'http://' + lms_base
        else:
            lms_base = 'https://' + lms_base
        url = reverse('lti1p3_tool_launch_deep_link', kwargs={
            'token': str(obj.url_token)
        })
        return f"{lms_base}{url}"

    lti_dl_url.short_description = 'Deep Link URL'


class LtiDeepLinkCourseAdmin(admin.ModelAdmin):
    search_fields = ('lti_deep_link__title', 'lti_deep_link__url_token', 'lti_deep_link__lti_tool__title',)
    list_display = ('id', 'lti_deep_link', 'course_key')
    list_select_related = ("lti_deep_link",)


admin.site.register(LtiToolKey, LtiToolKeyAdmin)
admin.site.register(LtiPlatform, LtiPlatformAdmin)
admin.site.register(LtiTool, LtiToolAdmin)
admin.site.register(LtiExternalCourse, LtiExternalCourseAdmin)
admin.site.register(LtiUserEnrollment, LtiUserEnrollmentAdmin)
admin.site.register(LtiDeepLink, LtiDeepLinkAdmin)
admin.site.register(LtiDeepLinkCourse, LtiDeepLinkCourseAdmin)
