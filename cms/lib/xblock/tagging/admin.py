"""
Admin registration for tags models
"""
from django import forms
from django.contrib import admin
from django.utils.translation import ugettext_lazy as _
from .models import TagCategories, TagOrgTypes, TagAvailableValues
from student.roles import CourseStaffRole, CourseInstructorRole


class TagCategoriesForm(forms.ModelForm):
    """Form for add/edit tag category."""

    class Meta(object):
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
        super(TagCategoriesForm, self).__init__(*args, **kwargs)
        from credo_modules.models import OrganizationType

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
        res = super(TagCategoriesForm, self).save(*args, **kwargs)
        self.instance.set_org_types(self.cleaned_data.get('org_types', []))
        return res


class TagCategoriesAdmin(admin.ModelAdmin):
    """Admin for TagCategories"""
    form = TagCategoriesForm
    search_fields = ('name', 'title')
    list_display = ('id', 'name', 'title', 'editable_in_studio', 'role', 'scoped_by')


class TagAvailableValuesAdmin(admin.ModelAdmin):
    """Admin for TagAvailableValues"""
    list_display = ('id', 'category', 'course_id', 'org', 'value')


admin.site.register(TagCategories, TagCategoriesAdmin)
admin.site.register(TagAvailableValues, TagAvailableValuesAdmin)
