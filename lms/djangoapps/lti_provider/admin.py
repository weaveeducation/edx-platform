"""
Admin interface for LTI Provider app.
"""

from django.contrib import admin

from .models import LtiConsumer, OutcomeService, LtiUser, LtiContextId, GradedAssignment


class LtiConsumerAdmin(admin.ModelAdmin):
    """Admin for LTI Consumer"""
    search_fields = ('consumer_name', 'consumer_key', 'instance_guid')
    list_display = ('id', 'consumer_name', 'consumer_key', 'instance_guid')


class OutcomeServiceAdmin(admin.ModelAdmin):
    """Admin for Outcome Service"""
    search_fields = ('lis_outcome_service_url', 'lti_consumer__consumer_name')
    list_display = ('id', 'lis_outcome_service_url', 'get_consumer_id', 'get_consumer_name')
    list_display_links = None

    def get_consumer_id(self, obj):
        return obj.lti_consumer.id

    get_consumer_id.short_description = 'Consumer ID'
    get_consumer_id.admin_order_field = 'lti_consumer__id'

    def get_consumer_name(self, obj):
        return obj.lti_consumer.consumer_name

    get_consumer_name.short_description = 'Consumer Name'
    get_consumer_name.admin_order_field = 'lti_consumer__consumer_name'

    def has_add_permission(self, request, obj=None):
        return False

    def get_actions(self, request):
        return []


class ReadOnlyMixin(object):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class LtiUserAdmin(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'lti_consumer_info', 'lti_user_id', 'edx_user')
    search_fields = ['edx_user__username', 'edx_user__email', 'lti_user_id', 'lti_consumer__consumer_name']

    def lti_consumer_info(self, obj):
        return obj.lti_consumer.consumer_name + ' [id=' + str(obj.lti_consumer.id) + ']'


class LtiContextIdAdmin(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'user', 'course_key', 'usage_key', 'lti_version', 'value', 'properties')
    search_fields = ['user__username', 'user__email', 'course_key', 'usage_key']


class GradedAssignmentAdmin(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'user', 'course_key', 'usage_key', 'outcome_service_id',
                    'lis_result_sourcedid', 'lis_result_sourcedid_value')
    search_fields = ['user__username', 'user__email', 'course_key', 'usage_key']

    def outcome_service_id(self, obj):
        return str(obj.outcome_service.id)


admin.site.register(LtiConsumer, LtiConsumerAdmin)
admin.site.register(OutcomeService, OutcomeServiceAdmin)
admin.site.register(LtiUser, LtiUserAdmin)
admin.site.register(LtiContextId, LtiContextIdAdmin)
admin.site.register(GradedAssignment, GradedAssignmentAdmin)
