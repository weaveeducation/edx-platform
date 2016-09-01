"""
Admin registration for tags models
"""
from django.contrib import admin
from .models import TagCategories, TagAvailableValues


class TagCategoriesAdmin(admin.ModelAdmin):
    """Admin for TagCategories"""
    search_fields = ('name', 'title')
    list_display = ('id', 'name', 'title', 'editable_in_studio', 'scoped_by_course')


class TagAvailableValuesAdmin(admin.ModelAdmin):
    """Admin for TagAvailableValues"""
    list_display = ('id', 'category', 'course_id', 'value')


admin.site.register(TagCategories, TagCategoriesAdmin)
admin.site.register(TagAvailableValues, TagAvailableValuesAdmin)
