"""
Django models related to course groups functionality.
"""

import json
import logging

from django.contrib.auth.models import User
from django.db import models
from django.db import IntegrityError
from xmodule_django.models import CourseKeyField

log = logging.getLogger(__name__)


class CourseUserGroup(models.Model):
    """
    This model represents groups of users in a course.  Groups may have different types,
    which may be treated specially.  For example, a user can be in at most one cohort per
    course, and cohorts are used to split up the forums by group.
    """
    class Meta(object):  # pylint: disable=missing-docstring
        unique_together = (('name', 'course_id'), )

    name = models.CharField(max_length=255,
                            help_text=("What is the name of this group?  "
                                       "Must be unique within a course."))
    users = models.ManyToManyField(User, db_index=True, related_name='course_groups',
                                   help_text="Who is in this group?", through='CourseUserGroupMembership')

    # Note: groups associated with particular runs of a course.  E.g. Fall 2012 and Spring
    # 2013 versions of 6.00x will have separate groups.
    course_id = CourseKeyField(
        max_length=255,
        db_index=True,
        help_text="Which course is this group associated with?",
    )

    # For now, only have group type 'cohort', but adding a type field to support
    # things like 'question_discussion', 'friends', 'off-line-class', etc
    COHORT = 'cohort'
    GROUP_TYPE_CHOICES = ((COHORT, 'Cohort'),)
    group_type = models.CharField(max_length=20, choices=GROUP_TYPE_CHOICES)

    @classmethod
    def create(cls, name, course_id, group_type=COHORT):
        """
        Create a new course user group.

        Args:
            name: Name of group
            course_id: course id
            group_type: group type
        """
        return cls.objects.get_or_create(
            course_id=course_id,
            group_type=group_type,
            name=name
        )

class CourseUserGroupMembership(models.Model):
    """Used internally to enforce our particular definition of uniqueness"""

    class Meta(object):  # pylint: disable=missing-docstring
        #used to ensure only one version of a given membership exists
        unique_together = (('user', 'course_user_group'), )

    def save(self, *args, **kwargs):
"""
skip all of this race condition handling if:
    -the user group being joined is not a cohort
    -this is the initial save (v0) of a membership (prevents infinite loop)
"""
        if self.course_user_group.group_type != CourseUserGroup.COHORT or self.version == 0:
            if 'get_previous' in kwargs:
                del kwargs['get_previous']
            super(CourseUserGroupMembership, self).save(*args, **kwargs)
            return

#set up the loop that will allow failed race condition cases to be retried
        self.trying_to_save = True
        while(self.trying_to_save):

#first, see if any cohort memberships already exist in this course for this user
            try:
                saved_membership = CourseUserGroupMembership.objects.exclude(
                    id = self.id
                ).get(
                    user__id = self.user.id,
                    course_user_group__course_id = self.course_user_group.course_id,
                    course_user_group__group_type = CourseUserGroup.COHORT
                )

"""
If none exists, create a static "first membership" for the course. This is
needed because we can guarantee multiprocess safety when changing a user's
membership in a course, but not when creating it from nothing. By forcing
all "first memberships" to be this one, with a static name, we allow the
CourseUserGroup unique_together constraint to solve the problem for us.
"""
            except CourseUserGroupMembership.DoesNotExist:
                try:
                    dummy_group = CourseUserGroup.objects.get(
                        name="_db_internal_",
                        course_id=self.course_user_group.course_id,
                        group_type=CourseUserGroup.COHORT
                    )
                except CourseUserGroup.DoesNotExist:
                    dummy_group = CourseUserGroup(
                        name="_db_internal_",
                        course_id=self.course_user_group.course_id,
                        group_type=CourseUserGroup.COHORT
                    )
                new_membership = CourseUserGroupMembership(user=self.user, course_user_group=dummy_group)
                try:
                    new_membership.save()
                except Exception: #TODO: verify error class here
                    pass #we're going to continue either way
                continue

"""
if we've made it to this point, we're assured of having a value in
saved_membership. So a previous version of the unique (user, cohort)
combination has been found.
"""
#raise ValueError if trying to rejoin the same cohort (previous behavior)
            if saved_membership.course_user_group == self.course_user_group:
                raise ValueError("User {user_name} already present in cohort {cohort_name}".format(
                    user_name=self.user.username,
                    cohort_name=self.course_user_group.name
                ))
#else save the previous cohort information, it's included in the emitted event
            elif 'get_previous' in kwargs and kwargs['get_previous']:
                self.previous_cohort = saved_membership.course_user_group
                self.previous_cohort_name = saved_membership.course_user_group.name
                self.previous_cohort_id = saved_membership.course_user_group.id

"""
now, update the "saved" membership with the new value we want it to have. By
using filter().update(), we get a single query that will find the "current"
version saved_membership, and change it's version to +1. Since this is atomic,
there's no way for 2 parallel processes to update simultaneously - the second
filter() will not match anything after version is incremented.
"""
            saved_membership.course_user_group = self.course_user_group
            updated = CourseUserGroupMembership.objects.filter(
                id = saved_membership.id,
                version = saved_membership.version
            ).update(
                course_user_group = self.course_user_group,
                version = saved_membership.version + 1
            )
            if not updated:
#if nothing was updated, we hit the race condition. Try again!
                continue

#if we've made it here, huzzah! we successfully updated the (user, cohort) membership
            self.trying_to_save = False
#end save(), everything below here are just fields/properties of CourseUserGroupMembership

    id = models.AutoField(primary_key=True)
    course_user_group = models.ForeignKey(CourseUserGroup)
    user = models.ForeignKey(User)
    version = models.IntegerField(default=0)

    previous_cohort = None
    previous_cohort_name = None
    previous_cohort_id = None


class CourseUserGroupPartitionGroup(models.Model):
    """
    Create User Partition Info.
    """
    course_user_group = models.OneToOneField(CourseUserGroup)
    partition_id = models.IntegerField(
        help_text="contains the id of a cohorted partition in this course"
    )
    group_id = models.IntegerField(
        help_text="contains the id of a specific group within the cohorted partition"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CourseCohortsSettings(models.Model):
    """
    This model represents cohort settings for courses.
    """
    is_cohorted = models.BooleanField(default=False)

    course_id = CourseKeyField(
        unique=True,
        max_length=255,
        db_index=True,
        help_text="Which course are these settings associated with?",
    )

    _cohorted_discussions = models.TextField(db_column='cohorted_discussions', null=True, blank=True)  # JSON list

    # pylint: disable=invalid-name
    always_cohort_inline_discussions = models.BooleanField(default=True)

    @property
    def cohorted_discussions(self):
        """Jsonify the cohorted_discussions"""
        return json.loads(self._cohorted_discussions)

    @cohorted_discussions.setter
    def cohorted_discussions(self, value):
        """Un-Jsonify the cohorted_discussions"""
        self._cohorted_discussions = json.dumps(value)


class CourseCohort(models.Model):
    """
    This model represents cohort related info.
    """
    course_user_group = models.OneToOneField(CourseUserGroup, unique=True, related_name='cohort')

    RANDOM = 'random'
    MANUAL = 'manual'
    ASSIGNMENT_TYPE_CHOICES = ((RANDOM, 'Random'), (MANUAL, 'Manual'),)
    assignment_type = models.CharField(max_length=20, choices=ASSIGNMENT_TYPE_CHOICES, default=MANUAL)

    @classmethod
    def create(cls, cohort_name=None, course_id=None, course_user_group=None, assignment_type=MANUAL):
        """
        Create a complete(CourseUserGroup + CourseCohort) object.

        Args:
            cohort_name: Name of the cohort to be created
            course_id: Course Id
            course_user_group: CourseUserGroup
            assignment_type: 'random' or 'manual'
        """
        if course_user_group is None:
            course_user_group, __ = CourseUserGroup.create(cohort_name, course_id)

        course_cohort, __ = cls.objects.get_or_create(
            course_user_group=course_user_group,
            defaults={'assignment_type': assignment_type}
        )

        return course_cohort
