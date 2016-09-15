import json
from django.contrib.auth.models import User
from django.db import models
from xmodule_django.models import CourseKeyField

from credo_modules.utils import additional_profile_fields_hash
from student.models import CourseEnrollment


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
        profiles = cls.objects.filter(course_id=course_id)
        result = {}
        for profile in profiles:
            result[profile.user_id] = json.loads(profile.meta)
        return result


def user_must_fill_additional_profile_fields(course, user):
    course_key = course.id
    if course.credo_additional_profile_fields and user.email.endswith('@credomodules.com') \
            and CourseEnrollment.is_enrolled(user, course_key):
        fields_version = additional_profile_fields_hash(course.credo_additional_profile_fields)
        profiles = CredoModulesUserProfile.objects.filter(user=user, course_id=course_key)
        if len(profiles) == 0 or profiles[0].fields_version != fields_version:
            return True
    return False
