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
import re

from django.contrib.auth import get_user_model
from django.db import models, IntegrityError, transaction
from django.utils import timezone
from openedx.core.lib.hash_utils import short_token

from opaque_keys.edx.django.models import CourseKeyField, UsageKeyField
from openedx.core.djangolib.fields import CharNullField

User = get_user_model()
log = logging.getLogger("edx.lti_provider")
log_json = logging.getLogger("credo_json")

LTI1p1 = '1.1'
LTI1p3 = '1.3'

LTI_VERSIONS = (
    (LTI1p1, 'LTI 1.1'),
    (LTI1p3, 'LTI 1.3'),
)


class LmsType(object):
    CANVAS = 'canvas'
    SAKAI = 'sakai'
    BLACKBOARD = 'blackboard'
    UNKNOWN = 'unknown'


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
    lti_strict_mode = models.BooleanField(null=True, blank=True, help_text="More strict validation rules "
                                                                           "for requests from the consumer LMS "
                                                                           "(according to the LTI standard) ."
                                                                           "Choose 'Yes' to enable strict mode.")
    allow_to_add_instructors_via_lti = models.BooleanField(null=True, blank=True,
                                                           help_text="Automatically adds "
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
    lti_consumer = models.ForeignKey(LtiConsumer, on_delete=models.CASCADE)


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
    user = models.ForeignKey(User, db_index=True, on_delete=models.CASCADE)
    course_key = CourseKeyField(max_length=255, db_index=True)
    usage_key = UsageKeyField(max_length=255, db_index=True)
    outcome_service = models.ForeignKey(OutcomeService, on_delete=models.CASCADE)
    lis_result_sourcedid = models.CharField(max_length=255, db_index=True)
    lis_result_sourcedid_value = models.TextField(null=True)
    version_number = models.IntegerField(default=0)
    disabled = models.BooleanField(default=False)

    class Meta:
        unique_together = ('outcome_service', 'lis_result_sourcedid')


class LtiUser(models.Model):
    """
    Model mapping the identity of an LTI user to an account on the edX platform.
    The LTI user_id field is guaranteed to be unique per LTI consumer (per
    to the LTI spec), so we guarantee a unique mapping from LTI to edX account
    by using the lti_consumer/lti_user_id tuple.
    """
    lti_consumer = models.ForeignKey(LtiConsumer, on_delete=models.CASCADE)
    lti_user_id = models.CharField(max_length=255)
    edx_user = models.OneToOneField(User, on_delete=models.CASCADE)

    class Meta:
        unique_together = ('lti_consumer', 'lti_user_id')


class GradedAssignmentLock(models.Model):
    graded_assignment_id = models.IntegerField(null=False)
    created = models.DateTimeField()
    lti_version = models.CharField(max_length=10, choices=LTI_VERSIONS, default=LTI1p1)

    class Meta:
        unique_together = ('graded_assignment_id', 'lti_version')

    @classmethod
    def create(cls, graded_assignment_id, lti_version=None):
        if not lti_version:
            lti_version = LTI1p1
        try:
            with transaction.atomic():
                lock = GradedAssignmentLock(graded_assignment_id=graded_assignment_id,
                                            created=timezone.now(),
                                            lti_version=lti_version)
                lock.save()
                return lock
        except IntegrityError:
            try:
                lock = GradedAssignmentLock.objects.get(graded_assignment_id=graded_assignment_id,
                                                        lti_version=lti_version)
                if lock:
                    time_diff = timezone.now() - lock.created
                    if time_diff.total_seconds() > 60:  # 1 min
                        return lock
            except GradedAssignmentLock.DoesNotExist:
                pass
            return False

    @classmethod
    def remove(cls, graded_assignment_id, lti_version=None):
        if not lti_version:
            lti_version = LTI1p1
        GradedAssignmentLock.objects.filter(graded_assignment_id=graded_assignment_id,
                                            lti_version=lti_version).delete()


class LtiContextId(models.Model):
    user = models.ForeignKey(User, db_index=True, on_delete=models.CASCADE)
    course_key = CourseKeyField(max_length=255, db_index=True)
    usage_key = UsageKeyField(max_length=255, db_index=True)
    lti_version = models.CharField(max_length=10, choices=LTI_VERSIONS, default=LTI1p1)
    value = models.TextField()
    properties = models.TextField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def has_properties(self):
        return True if self.properties else False

    def set_properties(self, value):
        self.properties = json.dumps(value)

    def get_properties(self):
        if self.properties:
            return json.loads(self.properties)
        return {}

    class Meta:
        unique_together = ('course_key', 'usage_key', 'user', 'lti_version')


class SendScoresLock:

    def __init__(self, graded_assignment_id, lti_version=None):
        self.graded_assignment_id = graded_assignment_id
        self.lti_version = lti_version if lti_version else LTI1p1
        self.lock = False

    def __enter__(self):
        while True:
            self.lock = GradedAssignmentLock.create(self.graded_assignment_id, self.lti_version)
            if self.lock:
                return self.lock
            else:
                time.sleep(2)  # 2 seconds

    def __exit__(self, *args):
        GradedAssignmentLock.remove(self.graded_assignment_id, self.lti_version)


def log_lti(action, user_id, message, course_id, is_error,
            assignment=None, grade=None, task_id=None, response_body=None, request_body=None,
            lis_outcome_service_url=None, lti_version='1.1', **kwargs):
    hostname = platform.node().split(".")[0]

    if request_body and isinstance(request_body, bytes):
        request_body = request_body.decode("utf-8")
    if response_body and isinstance(response_body, bytes):
        response_body = response_body.decode("utf-8")

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
        'lis_outcome_service_url': lis_outcome_service_url,
        'lti_version': lti_version
    }
    data.update(kwargs)
    log_json.info(json.dumps(data))


def log_lti_launch(course_id, usage_id, http_response, user_id=None, assignment=None, new_tab_check=False,
                   params=None, page_name=None):
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
        'http_response': int(http_response),
        'page': 'block_page' if usage_id else 'progress_page',
        'lti_version': '1.1'
    }
    if page_name:
        data['page_name'] = page_name
    if params:
        for k, v in params.items():
            pk = 'lti_user_id' if k == 'user_id' else k
            data[pk] = '%s' % v
    log_json.info(json.dumps(data))


def detect_lms_type(post_data):
    if LmsType.CANVAS in post_data.get('tool_consumer_instance_guid', ''):
        return LmsType.CANVAS
    elif LmsType.BLACKBOARD in post_data.get('lis_outcome_service_url', '')\
            or LmsType.BLACKBOARD in post_data.get('launch_presentation_return_url', ''):
        return LmsType.BLACKBOARD
    elif LmsType.SAKAI in post_data.get('tool_consumer_info_product_family_code', '')\
            or LmsType.SAKAI in post_data.get('ext_lms', '')\
            or LmsType.SAKAI in post_data.get('tool_consumer_instance_guid', ''):
        return LmsType.SAKAI
    return None


def get_rutgers_code(post_data, lms_type=None):
    if not lms_type:
        lms_type = detect_lms_type(post_data)
    context_label = post_data.get('context_label', '')

    if context_label:
        # RBHS campus, examples:
        # EPID0652J030 (Epid of Chronic Diseases)
        # HVAD5020G001 (HIV SM II DOC DT HLT IMP HIV C)
        context_label_lst = context_label.split(' ')
        for cl in context_label_lst:
            if len(cl) == 12 and re.match('^[a-zA-Z]{4}[0-9]{4}[a-zA-Z]{1}[0-9]{3}$', cl):
                return 'rbhs'

    rcode = None
    if lms_type == LmsType.SAKAI:
        # Sakai - lis_course_offier_sourcedid ( Example: 2020:9:01:090:220:08: )
        lis_course_offering_sourcedid = post_data.get('lis_course_offering_sourcedid', '')
        if lis_course_offering_sourcedid:
            lis_course_offering_sourcedid_lst = lis_course_offering_sourcedid.split(':')
            if len(lis_course_offering_sourcedid_lst) > 2:
                rcode = lis_course_offering_sourcedid_lst[2]
    elif lms_type == LmsType.CANVAS:
        # Canvas - context_label ( Example: 01:355:303:06 WRTG FOR BUS&PROFESS )
        if context_label:
            context_label_lst = context_label.split(':')
            if len(context_label_lst) > 1:
                rcode = context_label_lst[0]
    elif lms_type == LmsType.BLACKBOARD:
        # Blackboard - context_label ( Example: 202092152525462 )
        if context_label and len(context_label) > 6:
            rcode = context_label[5:7]

    if rcode and rcode.isnumeric() and len(rcode) == 2:
        return rcode

    return None
