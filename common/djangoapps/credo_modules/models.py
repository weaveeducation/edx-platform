import json
from django.contrib.auth.models import User
from django.db import models
from openedx.core.djangoapps.xmodule_django.models import CourseKeyField

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


class StudentAttributesRegistrationModel(object):
    """
    Helper model-like object to save registration properties.
    """
    data = None
    user = None

    def __init__(self, data):
        self.data = data

    def save(self):
        if self.data:
            for values in self.data:
                values['user'] = self.user
                CredoStudentProperties(**values).save()


class CredoStudentProperties(models.Model):
    """
    This table contains info about the custom student properties.
    """
    class Meta(object):
        db_table = "credo_student_properties"
        ordering = ('user', 'course_id', 'name')

    user = models.ForeignKey(User)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)
    name = models.CharField(max_length=255, db_index=True)
    value = models.CharField(max_length=255)


class RegistrationPropertiesPerMicrosite(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', unique=True)
    domain = models.CharField(max_length=255, verbose_name='Microsite Domain Name', unique=True)
    data = models.TextField(
        verbose_name="Registration Properties",
        help_text="Config in JSON format",
    )

    class Meta(object):
        db_table = "credo_registration_properties"
        verbose_name = "registration properties item"
        verbose_name_plural = "registration properties per microsite"


def user_must_fill_additional_profile_fields(course, user, block=None):
    graded = block.graded if block else False
    course_key = course.id
    if graded and course.credo_additional_profile_fields and user.email.endswith('@credomodules.com') \
            and CourseEnrollment.is_enrolled(user, course_key):
        fields_version = additional_profile_fields_hash(course.credo_additional_profile_fields)
        profiles = CredoModulesUserProfile.objects.filter(user=user, course_id=course_key)
        if len(profiles) == 0 or profiles[0].fields_version != fields_version:
            return True
    return False
