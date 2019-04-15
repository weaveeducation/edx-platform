"""
Django Models for tags
"""
from django.db import models
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import ValidationError
from opaque_keys.edx.django.models import CourseKeyField


class TagCategories(models.Model):

    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    editable_in_studio = models.BooleanField(default=False, verbose_name=_("Editable in studio"))
    scoped_by = models.CharField(max_length=255, null=True, blank=True, verbose_name=_("Scoped by"))
    role = models.CharField(max_length=64, null=True, blank=True, verbose_name=_("Access role"))

    class Meta(object):
        app_label = "tagging"
        ordering = ('title',)
        verbose_name = "tag category"
        verbose_name_plural = "tag categories"

    def clean(self):
        self.name = self.name.strip()

        if self.name == "":
            raise ValidationError(_("Name field is required"))

        if not all(ord(char) < 128 for char in self.name):
            raise ValidationError(_("Name field contains unacceptable characters"))

    def __unicode__(self):
        return u"[TagCategories] {}: {}".format(self.name, self.title)

    def get_values(self, course_id=None, org=None):
        kwargs = {
            'category': self
        }
        if org:
            kwargs['org'] = org
        if course_id:
            kwargs['course_id'] = course_id
        return [t.value for t in TagAvailableValues.objects.filter(**kwargs).order_by('value')]


class TagAvailableValues(models.Model):

    category = models.ForeignKey(TagCategories, db_index=True)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)
    org = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    value = models.CharField(max_length=255, help_text="Limited to 255 symbols")

    class Meta(object):
        app_label = "tagging"
        ordering = ('id',)
        verbose_name = "available tag value"

    def clean(self):
        super(TagAvailableValues, self).clean()

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

    def __unicode__(self):
        return u"[TagAvailableValues] {}: {}".format(self.category, self.value)
