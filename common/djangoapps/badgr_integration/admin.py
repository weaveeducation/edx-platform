from django.contrib import admin, messages
from django.http import HttpResponseRedirect
from .models import Assertion, Badge, Configuration, Issuer
from .service import badges_sync


class ReadOnlyMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AssertionForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'external_id', 'user', 'badge', 'created_at')


class BadgeForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'title', 'issuer', 'external_id', 'is_active', 'url', 'image_url', 'created_at', 'updated_at')
    actions = ['badgr_sync', ]

    def badgr_sync(self, request):
        created, updated, deactivated = badges_sync()
        messages.info(
            request, f'Badgr Integration is done: created: {created}, updated: {updated}, deactivated: {deactivated}')

    def changelist_view(self, request, extra_context=None):
        if 'action' in request.POST and request.POST['action'] == 'badgr_sync':
            self.badgr_sync(request)
            return HttpResponseRedirect(request.get_full_path())
        return super().changelist_view(request, extra_context)

    badgr_sync.short_description = 'Synchronization with Badgr'
    badgr_sync.acts_on_all = True


class ConfigurationForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'updated_at')

    def get_actions(self, request):
        return []

    def has_change_permission(self, request, obj=None):
        return True


class IssuerForm(ReadOnlyMixin, admin.ModelAdmin):
    list_display = ('id', 'title', 'external_id', 'is_active', 'url', 'image_url', 'created_at', 'updated_at')


admin.site.register(Assertion, AssertionForm)
admin.site.register(Badge, BadgeForm)
admin.site.register(Configuration, ConfigurationForm)
admin.site.register(Issuer, IssuerForm)


