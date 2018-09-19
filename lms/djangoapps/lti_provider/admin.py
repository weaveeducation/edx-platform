"""
Admin interface for LTI Provider app.
"""

from django.contrib import admin

from .models import LtiConsumer, OutcomeService


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


admin.site.register(LtiConsumer, LtiConsumerAdmin)
admin.site.register(OutcomeService, OutcomeServiceAdmin)
