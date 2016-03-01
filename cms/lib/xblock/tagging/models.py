"""
Django Model for tags
"""
from django.db import models
from xmodule_django.models import CourseKeyField


class AvailableTags(models.Model):

    TAG_CATEGORIES = (('difficulty_tag', 'difficulty_tag'),
                      ('learning_outcome_tag', 'learning_outcome_tag'))

    course_id = CourseKeyField(max_length=255, db_index=True)
    category = models.CharField(max_length=32, choices=TAG_CATEGORIES, db_index=True)
    tag = models.CharField(max_length=255)

    class Meta(object):
        unique_together = (('course_id', 'category', 'tag'),)
        ordering = ('id',)

    def __unicode__(self):
        return (
            "[AvailableTags] {}: {} {}"
        ).format(self.course_id, self.category, self.tag)
