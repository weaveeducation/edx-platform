from django.contrib import admin
from instructor.models import InstructorAvailableSections


def available_sections_bulk_action(field, is_set):
    prefix = 'Set' if is_set else 'Unset'
    name = field.name.__str__()

    def action(modeladmin, request, queryset):
        queryset.update(**{name: is_set})

    action.short_description = prefix + ' [' + field.verbose_name + '] for selected objects'
    action.__name__ = prefix + name
    return action


class InstructorAvailableSectionsAdmin(admin.ModelAdmin):
    bulk_fields_names = ['show_course_info', 'show_membership', 'show_cohort', 'show_student_admin',
                                  'show_data_download', 'show_email', 'show_analytics', 'show_studio_link']

    list_display = ['user'] + bulk_fields_names

    model_fields = InstructorAvailableSections._meta.get_fields()
    bulk_fields = [field for field in model_fields if field.name.__str__() in bulk_fields_names]

    bulk_set_actions = [available_sections_bulk_action(field, is_set=True) for field in bulk_fields]
    bulk_unset_actions = [available_sections_bulk_action(field, is_set=False) for field in bulk_fields]

    actions = bulk_set_actions + bulk_unset_actions


admin.site.register(InstructorAvailableSections, InstructorAvailableSectionsAdmin)
