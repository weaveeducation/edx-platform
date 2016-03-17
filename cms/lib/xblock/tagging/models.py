"""
Django Model for tags
"""
from django.db import models


class TagCategories(models.Model):

    name = models.CharField(max_length=255)
    title = models.CharField(max_length=255)

    class Meta(object):
        app_label = "tagging"
        ordering = ('title',)

    def __unicode__(self):
        return "[TagCategories] {}: {}".format(self.name, self.title)

    def get_values(self):
        return [t.value for t in TagAvailableValues.objects.filter(category=self)]


class TagAvailableValues(models.Model):

    category = models.ForeignKey(TagCategories, db_index=True)
    value = models.CharField(max_length=255)

    class Meta(object):
        app_label = "tagging"
        ordering = ('id',)

    def __unicode__(self):
        return "[TagAvailableValues] {}: {}".format(self.category, self.value)