"""
Database models for the LTI provider feature.

This app uses migrations. If you make changes to this model, be sure to create
an appropriate migration file and check it in at the same time as your model
changes. To do that,

1. Go to the edx-platform dir
2. ./manage.py lms schemamigration lti_provider --auto "description" --settings=devstack
"""
import logging
import time
import datetime
import json
import platform

from django.contrib.auth.models import User
from django.db import models, IntegrityError, transaction
from django.utils import timezone
from provider.utils import short_token

from opaque_keys.edx.django.models import CourseKeyField, UsageKeyField
from openedx.core.djangolib.fields import CharNullField

log = logging.getLogger("edx.lti_provider")
log_json = logging.getLogger("credo_json")


class LtiConsumer(models.Model):
    """
    Database model representing an LTI consumer. This model stores the consumer
    specific settings, such as the OAuth key/secret pair and any LTI fields
    that must be persisted.
    """
    consumer_name = models.CharField(max_length=255, unique=True)
    consumer_key = models.CharField(max_length=32, unique=True, db_index=True, default=short_token)
    consumer_secret = models.CharField(max_length=32, unique=True, default=short_token)
    instance_guid = CharNullField(max_length=255, blank=True, null=True, unique=True)
    lti_strict_mode = models.NullBooleanField(blank=True, help_text="More strict validation rules "
                                                                    "for requests from the consumer LMS "
                                                                    "(according to the LTI standard) ."
                                                                    "Choose 'Yes' to enable strict mode.")
    allow_to_add_instructors_via_lti = models.NullBooleanField(blank=True, help_text="Automatically adds "
                                                                                     "instructor role to the user "
                                                                                     "who came through the LTI if "
                                                                                     "some of these parameters: "
                                                                                     "'Administrator', 'Instructor', "
                                                                                     "'Staff' was passed. Choose 'Yes' "
                                                                                     "to enable this feature. ")

    @staticmethod
    def get_or_supplement(instance_guid, consumer_key):
        """
        The instance_guid is the best way to uniquely identify an LTI consumer.
        However according to the LTI spec, the instance_guid field is optional
        and so cannot be relied upon to be present.

        This method first attempts to find an LtiConsumer by instance_guid.
        Failing that, it tries to find a record with a matching consumer_key.
        This can be the case if the LtiConsumer record was created as the result
        of an LTI launch with no instance_guid.

        If the instance_guid is now present, the LtiConsumer model will be
        supplemented with the instance_guid, to more concretely identify the
        consumer.

        In practice, nearly all major LTI consumers provide an instance_guid, so
        the fallback mechanism of matching by consumer key should be rarely
        required.
        """
        consumer = None
        if instance_guid:
            try:
                consumer = LtiConsumer.objects.get(instance_guid=instance_guid)
            except LtiConsumer.DoesNotExist:
                # The consumer may not exist, or its record may not have a guid
                pass

        # Search by consumer key instead of instance_guid. If there is no
        # consumer with a matching key, the LTI launch does not have permission
        # to access the content.
        if not consumer:
            consumer = LtiConsumer.objects.get(
                consumer_key=consumer_key,
            )

        # Add the instance_guid field to the model if it's not there already.
        if instance_guid and not consumer.instance_guid:
            consumer.instance_guid = instance_guid
            consumer.save()
        return consumer


class OutcomeService(models.Model):
    """
    Model for a single outcome service associated with an LTI consumer. Note
    that a given consumer may have more than one outcome service URL over its
    lifetime, so we need to store the outcome service separately from the
    LtiConsumer model.

    An outcome service can be identified in two ways, depending on the
    information provided by an LTI launch. The ideal way to identify the service
    is by instance_guid, which should uniquely identify a consumer. However that
    field is optional in the LTI launch, and so if it is missing we can fall
    back on the consumer key (which should be created uniquely for each consumer
    although we don't have a technical way to guarantee that).

    Some LTI-specified fields use the prefix lis_; this refers to the IMS
    Learning Information Services standard from which LTI inherits some
    properties
    """
    lis_outcome_service_url = models.CharField(max_length=255, unique=True)
    lti_consumer = models.ForeignKey(LtiConsumer)


class GradedAssignment(models.Model):
    """
    Model representing a single launch of a graded assignment by an individual
    user. There will be a row created here only if the LTI consumer may require
    a result to be returned from the LTI launch (determined by the presence of
    the lis_result_sourcedid parameter in the launch POST). There will be only
    one row created for a given usage/consumer combination; repeated launches of
    the same content by the same user from the same LTI consumer will not add
    new rows to the table.

    Some LTI-specified fields use the prefix lis_; this refers to the IMS
    Learning Information Services standard from which LTI inherits some
    properties
    """
    user = models.ForeignKey(User, db_index=True)
    course_key = CourseKeyField(max_length=255, db_index=True)
    usage_key = UsageKeyField(max_length=255, db_index=True)
    outcome_service = models.ForeignKey(OutcomeService)
    lis_result_sourcedid = models.CharField(max_length=255, db_index=True)
    version_number = models.IntegerField(default=0)

    class Meta(object):
        unique_together = ('outcome_service', 'lis_result_sourcedid')


class LtiUser(models.Model):
    """
    Model mapping the identity of an LTI user to an account on the edX platform.
    The LTI user_id field is guaranteed to be unique per LTI consumer (per
    to the LTI spec), so we guarantee a unique mapping from LTI to edX account
    by using the lti_consumer/lti_user_id tuple.
    """
    lti_consumer = models.ForeignKey(LtiConsumer)
    lti_user_id = models.CharField(max_length=255)
    edx_user = models.OneToOneField(User)

    class Meta(object):
        unique_together = ('lti_consumer', 'lti_user_id')


class GradedAssignmentLock(models.Model):
    graded_assignment_id = models.IntegerField(null=False, unique=True)
    created = models.DateTimeField()

    @classmethod
    def create(cls, graded_assignment_id):
        try:
            with transaction.atomic():
                lock = GradedAssignmentLock(graded_assignment_id=graded_assignment_id, created=timezone.now())
                lock.save()
                return lock
        except IntegrityError:
            try:
                lock = GradedAssignmentLock.objects.get(graded_assignment_id=graded_assignment_id)
                if lock:
                    time_diff = timezone.now() - lock.created
                    if time_diff.total_seconds() > 60:  # 1 min
                        return lock
            except GradedAssignmentLock.DoesNotExist:
                pass
            return False

    @classmethod
    def remove(cls, graded_assignment_id):
        GradedAssignmentLock.objects.filter(graded_assignment_id=graded_assignment_id).delete()


class LtiContextId(models.Model):
    user = models.ForeignKey(User, db_index=True)
    course_key = CourseKeyField(max_length=255, db_index=True)
    usage_key = UsageKeyField(max_length=255, db_index=True)
    value = models.TextField()
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)


class SendScoresLock(object):

    def __init__(self, graded_assignment_id):
        self.graded_assignment_id = graded_assignment_id
        self.lock = False

    def __enter__(self):
        while True:
            self.lock = GradedAssignmentLock.create(self.graded_assignment_id)
            if self.lock:
                return self.lock
            else:
                time.sleep(2)  # 2 seconds

    def __exit__(self, *args):
        GradedAssignmentLock.remove(self.graded_assignment_id)


def log_lti(action, user_id, message, course_id, is_error,
            assignment=None, grade=None, task_id=None, response_body=None, request_body=None,
            lis_outcome_service_url=None, **kwargs):
    hostname = platform.node().split(".")[0]
    data = {
        'type': 'lti_task',
        'task_id': task_id,
        'hostname': hostname,
        'datetime': str(datetime.datetime.now()),
        'timestamp': time.time(),
        'is_error': is_error,
        'action': action,
        'user_id': int(user_id),
        'message': str(message),
        'course_id': str(course_id),
        'assignment_id': int(assignment.id) if assignment else None,
        'assignment_version_number': int(assignment.version_number) if assignment else None,
        'assignment_usage_key': str(assignment.usage_key) if assignment else None,
        'grade': grade,
        'request_body': request_body,
        'response_body': response_body,
        'lis_outcome_service_url': lis_outcome_service_url
    }
    data.update(kwargs)
    log_json.info(json.dumps(data))


def log_lti_launch(course_id, usage_id, http_response, user_id=None, assignment=None, new_tab_check=False, params=None):
    hostname = platform.node().split(".")[0]
    data = {
        'type': 'lti_launch',
        'hostname': hostname,
        'datetime': str(datetime.datetime.now()),
        'timestamp': time.time(),
        'course_id': str(course_id),
        'usage_id': usage_id,
        'edx_user_id': int(user_id) if user_id else None,
        'new_tab_check': new_tab_check,
        'assignment_id': int(assignment.id) if assignment else None,
        'assignment_version_number': int(assignment.version_number) if assignment else None,
        'assignment_usage_key': str(assignment.usage_key) if assignment else None,
        'http_response': int(http_response)
    }
    if params:
        for k, v in params.items():
            pk = 'lti_user_id' if k == 'user_id' else k
            data[pk] = '%s' % v
    log_json.info(json.dumps(data))
