from django.contrib import admin
from lms.djangoapps.instructor.models import InstructorAvailableSections


def available_sections_bulk_action(field, is_set):
    prefix = 'Set' if is_set else 'Unset'
    name = field.name.__str__()

    def action(modeladmin, request, queryset):
        queryset.update(**{name: is_set})

    action.short_description = prefix + ' [' + field.verbose_name + '] for selected objects'
    action.__name__ = prefix + name
    return action


instructor_admin_bulk_fields_names = [
    'show_course_info', 'show_membership', 'show_cohort', 'show_student_admin',
    'show_data_download', 'show_email', 'show_analytics', 'show_studio_link',
    'show_open_responses', 'show_lti_constructor', 'show_insights_link',
    'show_nw_help', 'show_discussions_management']


class InstructorAvailableSectionsAdmin(admin.ModelAdmin):
    search_fields = ('user__id', 'user__username', 'user__email',)
    raw_id_fields = ('user',)

    list_display = ['user'] + instructor_admin_bulk_fields_names
    list_display_links = None
    model_fields = InstructorAvailableSections._meta.get_fields()
    bulk_fields = [field for field in model_fields if field.name.__str__() in instructor_admin_bulk_fields_names]

    bulk_set_actions = [available_sections_bulk_action(field, is_set=True) for field in bulk_fields]
    bulk_unset_actions = [available_sections_bulk_action(field, is_set=False) for field in bulk_fields]

    actions = bulk_set_actions + bulk_unset_actions

    related_search_fields = {
        'user': ('user__email', 'user__username', 'user__first_name', 'user__last_name'),
    }


admin.site.register(InstructorAvailableSections, InstructorAvailableSectionsAdmin)
