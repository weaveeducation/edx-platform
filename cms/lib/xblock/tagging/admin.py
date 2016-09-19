"""
Admin registration for tags models
"""
from django import forms
from django.contrib import admin
from django.utils.translation import ugettext_lazy as _
from .models import TagCategories, TagAvailableValues
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
    role = forms.ChoiceField(choices=COURSE_ACCESS_ROLES, label=_("Access role"))

    def __init__(self, *args, **kwargs):
        super(TagCategoriesForm, self).__init__(*args, **kwargs)
        if not self.instance.role:
            self.initial['role'] = 'any'

    def clean_role(self):
        """
        Checking role.
        """
        if self.cleaned_data['role'] == 'any':
            return None
        return self.cleaned_data['role']


class TagCategoriesAdmin(admin.ModelAdmin):
    """Admin for TagCategories"""
    form = TagCategoriesForm
    search_fields = ('name', 'title')
    list_display = ('id', 'name', 'title', 'editable_in_studio', 'role', 'scoped_by_course')


class TagAvailableValuesAdmin(admin.ModelAdmin):
    """Admin for TagAvailableValues"""
    list_display = ('id', 'category', 'course_id', 'value')


admin.site.register(TagCategories, TagCategoriesAdmin)
admin.site.register(TagAvailableValues, TagAvailableValuesAdmin)
