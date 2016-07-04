import json
from django.contrib.auth.models import User
from django.db import models
from xmodule_django.models import CourseKeyField


class CredoModulesUserProfile(models.Model):
    """
    This table contains info about the credo modules student.
    """
    class Meta(object):
        db_table = "credo_modules_userprofile"
        ordering = ('user', 'course_id')
        unique_together = (('user', 'course_id'),)

    user = models.ForeignKey(User)
    course_id = CourseKeyField(max_length=255, db_index=True)
    meta = models.TextField(blank=True)  # JSON dictionary
    fields_version = models.CharField(max_length=80)

    @classmethod
    def users_with_additional_profile(cls, course_id):
        """Return a queryset of User for every user enrolled in the course."""
        profiles = cls.objects.filter(course_id=course_id)
        result = {}
        for profile in profiles:
            result[profile.user_id] = json.loads(profile.meta)
        return result
