"""
Admin registration for tags models
"""
from django import forms
from django.contrib import admin
from django.utils.translation import gettext_lazy as _
from .models import TagCategories, TagOrgTypes, TagAvailableValues
from common.djangoapps.student.roles import CourseStaffRole, CourseInstructorRole
from common.djangoapps.credo_modules.admin import ExportCsvMixin


class TagCategoriesForm(forms.ModelForm):
    """Form for add/edit tag category."""

    class Meta:
        model = TagCategories
        fields = '__all__'

    COURSE_ACCESS_ROLES = [('any', 'any'),
                           (CourseStaffRole.ROLE, CourseStaffRole.ROLE),
                           (CourseInstructorRole.ROLE, CourseInstructorRole.ROLE),
                           ('superuser', 'superuser')]
    SCOPED_BY = [('global', 'Global'), ('course', 'Course'), ('org', 'Org')]

    role = forms.ChoiceField(choices=COURSE_ACCESS_ROLES, label=_("Access role"))
    scoped_by = forms.ChoiceField(choices=SCOPED_BY, label=_("Scoped by"))
    org_types = forms.MultipleChoiceField(choices=[], label=_("Applicable for organization type "
                                                              "(applicable for all if nothing is selected)"),
                                          required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from common.djangoapps.credo_modules.models import OrganizationType

        org_types_values = []
        for o in OrganizationType.objects.all().order_by('title'):
            org_types_values.append((o.id, o.title))
        self.fields.get('org_types').choices = org_types_values

        if not self.instance.role:
            self.initial['role'] = 'any'
        if not self.instance.scoped_by:
            self.initial['scoped_by'] = 'global'
        if self.instance.id:
            self.initial['org_types'] = [t.org_type for t in TagOrgTypes.objects.filter(org=self.instance)]

    def clean_org_types(self):
        return self.cleaned_data['org_types'] if self.cleaned_data['org_types'] else None

    def clean_role(self):
        """
        Checking role.
        """
        if self.cleaned_data['role'] == 'any':
            return None
        return self.cleaned_data['role']

    def clean_scoped_by(self):
        """
        Checking scoped_by.
        """
        if self.cleaned_data['scoped_by'] == 'global':
            return None
        return self.cleaned_data['scoped_by']

    def save(self, *args, **kwargs):
        res = super().save(*args, **kwargs)
        self.instance.set_org_types(self.cleaned_data.get('org_types', []))
        return res


class TagCategoriesAdmin(admin.ModelAdmin):
    """Admin for TagCategories"""
    form = TagCategoriesForm
    search_fields = ('name', 'title')
    list_display = ('id', 'name', 'title', 'editable_in_studio', 'role', 'scoped_by')


class TagAvailableValuesAdmin(ExportCsvMixin, admin.ModelAdmin):
    """Admin for TagAvailableValues"""
    list_display = ('id', 'category', 'course_id', 'org', 'value')
    search_fields = ('id', 'category__name', 'category__title', 'course_id', 'org', 'value')
    csv_name = 'tag_values'
    actions = ('export_as_csv',)

    def get_csv_value(self, request, field_name, obj):
        if field_name == 'category':
            return obj.category.title
        return super().get_csv_value(request, field_name, obj)

    def get_export_csv_queryset(self, request):
        return TagAvailableValues.objects.all().order_by('category__title', 'value')


admin.site.register(TagCategories, TagCategoriesAdmin)
admin.site.register(TagAvailableValues, TagAvailableValuesAdmin)
