"""
Django Models for tags
"""
import re

from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from opaque_keys.edx.django.models import CourseKeyField


class TagCategories(models.Model):

    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    editable_in_studio = models.BooleanField(default=False, verbose_name=_("Editable in studio"))
    scoped_by = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Scoped by"))
    role = models.CharField(max_length=64, null=True, blank=True, verbose_name=_("Access role"))
    disable_superusers_tags = models.BooleanField(
        default=False, verbose_name=_("Prohibit users from removing outcomes added by super users"))

    _org_types = []

    class Meta(object):
        app_label = "tagging"
        ordering = ('title',)
        verbose_name = "tag category"
        verbose_name_plural = "tag categories"

    def clean(self):
        self.name = self.name.strip()

        if self.name == "":
            raise ValidationError(_("Name field is required"))

        pattern = re.compile("^[a-zA-Z0-9_]+$")
        if not pattern.match(self.name):
            raise ValidationError(_("Name field contains unacceptable characters or spaces"))

    def __str__(self):
        return "[TagCategories] {}: {}".format(self.name, self.title)

    def get_values(self, course_id=None, org=None):
        kwargs = {
            'category': self
        }
        if org:
            kwargs['org'] = org
        if course_id:
            kwargs['course_id'] = course_id
        return [t.value for t in TagAvailableValues.objects.filter(**kwargs).order_by('value')]

    def set_org_types(self, org_types):
        self._org_types = org_types

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self._org_types:
            TagOrgTypes.objects.filter(org=self).delete()
            for org_type_id in self._org_types:
                TagOrgTypes(
                    org=self,
                    org_type=int(org_type_id)
                ).save()


class TagOrgTypes(models.Model):
    org = models.ForeignKey(TagCategories, db_index=True, related_name='org_types', on_delete=models.CASCADE)
    org_type = models.IntegerField(null=False, blank=False, verbose_name=_("Organization type ID"))


class TagAvailableValues(models.Model):

    category = models.ForeignKey(TagCategories, db_index=True, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)
    org = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    value = models.CharField(max_length=255, help_text="Limited to 255 symbols")

    class Meta(object):
        app_label = "tagging"
        ordering = ('id',)
        verbose_name = "available tag value"

    def clean(self):
        super().clean()

        self.value = self.value.strip()

        if self.value == "":
            raise ValidationError(_("Value field is required"))

        if not all(ord(char) < 128 for char in self.value):
            raise ValidationError(_("Value field contains unacceptable characters"))

        if self.category.scoped_by == 'course' and not self.course_id:
            raise ValidationError(_('"course_id" is a required field (because in the related tag category'
                                    '"scoped_by: course" setting is enabled)'))
        if self.category.scoped_by == 'org' and not self.org:
            raise ValidationError(_('"org" is a required field (because in the related tag category'
                                    '"scoped_by: org" setting is enabled)'))

    def __str__(self):
        return "[TagAvailableValues] {}: {}".format(self.category, self.value)
