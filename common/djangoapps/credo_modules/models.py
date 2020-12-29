import logging
import time
import datetime
import json
import re
import uuid
from urllib.parse import urlparse
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.db import models, IntegrityError, OperationalError, transaction
from django.db.models import F
from django.db.models.signals import post_save, post_delete
from opaque_keys.edx.django.models import CourseKeyField
from opaque_keys.edx.keys import CourseKey, UsageKey
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils import timezone
from django.utils.timezone import utc
from django.utils.translation import ugettext_lazy as _
from model_utils.models import TimeStampedModel

from student.models import CourseEnrollment, CourseAccessRole, ENROLL_STATUS_CHANGE, EnrollStatusChange, UserProfile
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from edx_proctoring.models import ProctoredExamStudentAttempt
from organizations.models import Organization as EdxOrganization
from openedx.core.lib.hash_utils import short_token


log = logging.getLogger("course_usage")


class CredoModulesUserProfile(models.Model):
    """
    This table contains info about the credo modules student.
    """
    class Meta(object):
        db_table = "credo_modules_userprofile"
        ordering = ('user', 'course_id')
        unique_together = (('user', 'course_id'),)

    user = models.ForeignKey(User, on_delete=models.CASCADE)
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

    def converted_meta(self):
        try:
            meta_dict = json.loads(self.meta)
        except ValueError:
            meta_dict = {}
        return meta_dict


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


def get_enrollment_attributes(post_data, course_id, **kwargs):
    result = {}
    exclude_lti_properties = ['context_id', 'context_label']
    try:
        properties = EnrollmentPropertiesPerCourse.objects.get(course_id=course_id)
        try:
            enrollment_properties = json.loads(properties.data)
        except ValueError:
            return
        if enrollment_properties:
            for k, v in enrollment_properties.items():
                lti_key = v['lti'] if 'lti' in v else False
                default = v['default'] if 'default' in v and v['default'] else None
                if lti_key and lti_key not in exclude_lti_properties:
                    if lti_key in post_data:
                        result[k] = post_data[lti_key]
                    elif default:
                        result[k] = default
    except EnrollmentPropertiesPerCourse.DoesNotExist:
        pass

    for k, v in kwargs.items():
        if v:
            result[k] = v
    return result


ENROLLMENT_PROPERTIES_MAP = {
    'context_label': 'course'
}


def check_and_save_enrollment_attributes(properties, user, course_id):
    course_id_str = str(course_id)
    CredoStudentProperties.objects.filter(course_id=course_id, user=user).delete()
    tr = EnrollmentTrigger(
        user_id=user.id,
        course_id=course_id_str,
        event_type='update_props'
    )
    tr.save()

    for k, v in properties.items():
        prop_name = ENROLLMENT_PROPERTIES_MAP[k] if k in ENROLLMENT_PROPERTIES_MAP else k
        CredoStudentProperties(user=user, course_id=course_id, name=prop_name, value=v).save()
    set_custom_term(course_id, user)


def get_custom_term():
    return datetime.datetime.now().strftime("%B %Y")


def save_custom_term_student_property(term, user, course_id):
    return CredoStudentProperties.objects.get_or_create(user=user, course_id=course_id, name='term',
                                                        defaults={'value': term})


class CredoStudentProperties(models.Model):
    """
    This table contains info about the custom student properties.
    """
    class Meta(object):
        db_table = "credo_student_properties"
        ordering = ('user', 'course_id', 'name')

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)
    name = models.CharField(max_length=255, db_index=True)
    value = models.CharField(max_length=255)


def validate_json_props(value):
    try:
        json_data = json.loads(value)
        if json_data:
            for key in json_data:
                if not re.match(r'\w+$', key):
                    raise ValidationError(
                        '%(key)s should contain only alphanumeric characters and underscores',
                        params={'key': key},
                    )
    except ValueError:
        raise ValidationError('Invalid JSON')


class RegistrationPropertiesPerMicrosite(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', unique=True)
    domain = models.CharField(max_length=255, verbose_name='Microsite Domain Name', unique=True)
    data = models.TextField(
        verbose_name="Registration Properties",
        help_text="Config in JSON format",
        validators=[validate_json_props]
    )

    class Meta(object):
        db_table = "credo_registration_properties"
        verbose_name = "registration properties item"
        verbose_name_plural = "registration properties per microsite"


class RegistrationPropertiesPerOrg(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', unique=True)
    data = models.TextField(
        verbose_name="Registration Properties",
        help_text="Config in JSON format",
        validators=[validate_json_props]
    )

    class Meta(object):
        db_table = "credo_registration_properties_v2"
        verbose_name = "registration properties item"
        verbose_name_plural = "registration properties per org"


class EnrollmentPropertiesPerCourse(models.Model):
    course_id = CourseKeyField(db_index=True, max_length=255)
    data = models.TextField(
        verbose_name="Enrollment Properties",
        help_text="Config in JSON format",
        validators=[validate_json_props]
    )

    class Meta(object):
        db_table = "credo_enrollment_properties"
        verbose_name = "enrollment properties item"
        verbose_name_plural = "enrollment properties per course"


def user_must_fill_additional_profile_fields(course, user, block=None):
    graded = block.graded if block else False
    course_key = course.id
    if graded and course.credo_additional_profile_fields and user.is_authenticated and\
            user.email.endswith('@credomodules.com') and CourseEnrollment.is_enrolled(user, course_key):
        profiles = CredoModulesUserProfile.objects.filter(user=user, course_id=course_key)
        if len(profiles) == 0:
            return True
    return False


class TermPerOrg(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', null=False, blank=False, db_index=True)
    term = models.CharField(max_length=255, verbose_name='Term', null=False, blank=False)
    start_date = models.DateField(verbose_name='Start Date', null=False, blank=False)
    end_date = models.DateField(verbose_name='End Date', null=False, blank=False)

    def to_dict(self):
        return {
            'id': self.id,
            'org': self.org,
            'term': self.term,
            'start_date': self.start_date.strftime('%-m/%-d/%Y'),
            'end_date': self.end_date.strftime('%-m/%-d/%Y')
        }


def set_custom_term(course_id, user):
    save_custom_term_student_property(get_custom_term(), user, course_id)


@receiver(ENROLL_STATUS_CHANGE)
def add_custom_term_student_property_on_enrollment(sender, event=None, user=None, course_id=None, **kwargs):
    if event == EnrollStatusChange.enroll:
        set_custom_term(course_id, user)


def deadlock_db_retry(func):
    def func_wrapper(*args, **kwargs):
        max_attempts = 2
        current_attempt = 0
        while True:
            try:
                return func(*args, **kwargs)
            except OperationalError as e:
                if current_attempt < max_attempts:
                    current_attempt += 1
                    time.sleep(3)
                else:
                    log.error('Failed to save course usage: ' + str(e))
                    return

    return func_wrapper


class CourseUsage(models.Model):
    """
    Deprecated model. Please don't use it for insert new data
    """
    MODULE_TYPES = (('problem', 'problem'),
                    ('video', 'video'),
                    ('html', 'html'),
                    ('course', 'course'),
                    ('chapter', 'Section'),
                    ('sequential', 'Subsection'),
                    ('vertical', 'Vertical'),
                    ('library_content', 'Library Content'))

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)
    block_id = models.CharField(max_length=255, db_index=True, null=True)
    block_type = models.CharField(max_length=32, choices=MODULE_TYPES, null=True)
    usage_count = models.IntegerField(null=True)
    first_usage_time = models.DateTimeField(verbose_name='First Usage Time', null=True, blank=True)
    last_usage_time = models.DateTimeField(verbose_name='Last Usage Time', null=True, blank=True)
    session_ids = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = (('user', 'course_id', 'block_id'),)

    @classmethod
    def check_new_session(cls, request):
        browser_unique_user_id = get_unique_user_id(request)
        session_unique_user_id = request.session.get('course_usage_unique_user_id')
        if 'course_usage' not in request.session\
          or not isinstance(request.session['course_usage'], list)\
          or (browser_unique_user_id and browser_unique_user_id != session_unique_user_id):
            request.session['course_usage'] = []
            request.session['course_usage_unique_user_id'] = browser_unique_user_id
            request.session.modified = True

    @classmethod
    def is_viewed(cls, request, block_id):
        cls.check_new_session(request)
        return str(block_id) in request.session['course_usage']

    @classmethod
    def mark_viewed(cls, request, block_id):
        cls.check_new_session(request)
        request.session['course_usage'].append(str(block_id))
        request.session.modified = True

    @classmethod
    @deadlock_db_retry
    def _update_block_usage(cls, course_key, user_id, block_type, block_id):
        CourseUsage.objects.get(
            course_id=course_key,
            user_id=user_id,
            block_type=block_type,
            block_id=block_id
        )
        with transaction.atomic():
            CourseUsage.objects.filter(course_id=course_key, user_id=user_id,
                                       block_id=block_id, block_type=block_type) \
                    .update(last_usage_time=usage_dt_now(), usage_count=F('usage_count') + 1)

    @classmethod
    @deadlock_db_retry
    def _add_block_usage(cls, course_key, user_id, block_type, block_id):
        datetime_now = usage_dt_now()
        with transaction.atomic():
            cu = CourseUsage(
                course_id=course_key,
                user_id=user_id,
                usage_count=1,
                block_type=block_type,
                block_id=block_id,
                first_usage_time=datetime_now,
                last_usage_time=datetime_now
            )
            cu.save()
            return

    @classmethod
    def update_block_usage(cls, request, course_key, block_id, student_properties=None):
        if not cls.is_viewed(request, block_id) and hasattr(request, 'user') and request.user.is_authenticated:
            if not isinstance(course_key, CourseKey):
                course_key = CourseKey.from_string(course_key)
            if not isinstance(block_id, UsageKey):
                block_id = UsageKey.from_string(block_id)
            block_type = block_id.block_type
            block_id = str(block_id)

            try:
                cls._update_block_usage(course_key, request.user.id, block_type, block_id)
                CourseUsageLogEntry.add_new_log(request.user.id, str(course_key), str(block_id), str(block_type),
                                                student_properties)
            except CourseUsage.DoesNotExist:
                try:
                    cls._add_block_usage(course_key, request.user.id, block_type, block_id)
                    CourseUsageLogEntry.add_new_log(request.user.id, str(course_key), str(block_id), str(block_type),
                                                    student_properties)
                except IntegrityError:
                    # cls._update_block_usage(course_key, request.user.id,
                    #                        block_type, block_id, unique_user_id)
                    pass
            cls.mark_viewed(request, block_id)


class CourseUsageLogEntry(models.Model):
    user_id = models.IntegerField(db_index=True)
    course_id = models.CharField(max_length=255, db_index=True)
    block_id = models.CharField(max_length=255, null=True, blank=True)
    block_type = models.CharField(max_length=32, null=True, blank=True)
    time = models.DateTimeField(db_index=True)
    message = models.TextField()

    class Meta(object):
        db_table = "credo_usage_logs"

    @classmethod
    def add_new_log(cls, user_id, course_id, block_id, block_type, student_properties=None):
        message = json.dumps(student_properties if student_properties else {})
        new_item = cls(
            user_id=user_id,
            course_id=course_id,
            block_id=block_id,
            block_type=block_type,
            message=message,
            time=timezone.now()
        )
        new_item.save()


class OrganizationType(models.Model):
    title = models.CharField(max_length=255, verbose_name='Title', unique=True)
    constructor_lti_link = models.BooleanField(default=True, verbose_name='Display LTI link in Constructor')
    constructor_embed_code = models.BooleanField(default=True, verbose_name='Display embed code field in Constructor')
    constructor_direct_link = models.BooleanField(default=True, verbose_name='Display direct link in Constructor')
    insights_learning_outcomes = models.BooleanField(default=True, verbose_name='Display LO report in Credo Insights')
    insights_assessments = models.BooleanField(default=True, verbose_name='Display Assessment report in Credo Insights')
    insights_enrollment = models.BooleanField(default=True, verbose_name='Display Enrollment report in Credo Insights')
    insights_engagement = models.BooleanField(default=True, verbose_name='Display Engagement report in Credo Insights')
    instructor_dashboard_credo_insights = models.BooleanField(default=True, verbose_name='Show Credo Insights link'
                                                                                         ' in the Instructor Dashboard')
    enable_new_carousel_view = models.BooleanField(default=False, verbose_name='Enable new carousel view'
                                                                               ' (horizontal nav bar)')
    enable_page_level_engagement = models.BooleanField(default=False, verbose_name='Enable Page Level for Engagement '
                                                                                   'Statistic in Insights')
    enable_extended_progress_page = models.BooleanField(default=False, verbose_name='Enable Extended Progress Page')

    enable_item_analysis_reports = models.BooleanField(default=False, verbose_name='Enable Item Analysis Reports')

    available_roles = models.ManyToManyField('CustomUserRole', blank=True)

    exclude_properties = models.TextField(blank=True, verbose_name="Excluded property names in Insights",
                                          help_text="Values should be separated by commas")
    my_skills_page_lti_access = models.BooleanField(default=False, verbose_name='Display LTI link for My '
                                                                                'Skills/Progress LMS page '
                                                                                'in Constructor')

    class Meta:
        ordering = ['title']

    def __str__(self):
        return self.title

    @classmethod
    def get_all_constructor_fields(cls):
        return ['lti_link', 'embed_code', 'direct_link']

    def get_constructor_fields(self):
        data = []
        if self.constructor_lti_link:
            data.append('lti_link')
        if self.constructor_embed_code:
            data.append('embed_code')
        if self.constructor_direct_link:
            data.append('direct_link')
        return data

    @classmethod
    def get_all_insights_reports(cls):
        return ['learning_outcomes', 'assessments', 'enrollment', 'engagement']

    def get_insights_reports(self):
        data = []
        if self.insights_learning_outcomes:
            data.append('learning_outcomes')
        if self.insights_assessments:
            data.append('assessments')
        if self.insights_enrollment:
            data.append('enrollment')
        if self.insights_engagement:
            data.append('engagement')
        return data


class Organization(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', unique=True)
    default_frame_domain = models.CharField(max_length=255, verbose_name='Domain for LTI/Iframe/etc',
                                            help_text="Default value is https://frame.credocourseware.com "
                                                      "in case of empty field",
                                            null=True, blank=True,
                                            validators=[URLValidator()])
    org_type = models.ForeignKey(OrganizationType, on_delete=models.SET_NULL,
                                 related_name='org_type',
                                 null=True, blank=True, verbose_name='Org Type')

    class Meta:
        ordering = ['org']

    def __str__(self):
        return self.org

    def save(self, *args, **kwargs):
        if self.default_frame_domain:
            o = urlparse(self.default_frame_domain)
            self.default_frame_domain = o.scheme + '://' + o.netloc
        super(Organization, self).save(*args, **kwargs)

    def get_constructor_fields(self):
        if self.org_type:
            return self.org_type.get_constructor_fields()
        else:
            return OrganizationType.get_all_constructor_fields()

    def get_insights_reports(self):
        if self.org_type:
            return self.org_type.get_insights_reports()
        else:
            return OrganizationType.get_all_insights_reports()

    def get_item_analysis_reports(self):
        if self.org_type:
            return self.org_type.enable_item_analysis_reports
        else:
            return False

    def get_my_skills_page_lti_access(self):
        if self.org_type:
            return self.org_type.my_skills_page_lti_access
        else:
            return False

    def get_page_level_engagement(self):
        if self.org_type:
            return self.org_type.enable_page_level_engagement
        else:
            return False

    def get_exclude_properties(self):
        if self.org_type:
            return self.org_type.exclude_properties
        else:
            return ""

    def to_dict(self):
        return {
            'org': self.org,
            'default_frame_domain': self.default_frame_domain,
            'constructor_fields': self.get_constructor_fields(),
            'insights_reports': self.get_insights_reports(),
            'page_level_engagement': self.get_page_level_engagement(),
            'item_analysis_reports': self.get_item_analysis_reports(),
            'my_skills_page_lti_access': self.get_my_skills_page_lti_access(),
            'exclude_properties': self.get_exclude_properties(),
        }

    @property
    def is_carousel_view(self):
        if self.org_type is not None:
            return self.org_type.enable_new_carousel_view
        else:
            return False


class OrganizationTag(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    tag_name = models.CharField(max_length=255, verbose_name='Tag name')
    insights_view = models.BooleanField(default=True, verbose_name='Display on the Insights')
    progress_view = models.BooleanField(default=True, verbose_name='Display on the My Skills page')

    class Meta(object):
        ordering = ('org', 'tag_name')
        unique_together = (('org', 'tag_name'),)

    @classmethod
    def get_org_tags(cls, org_name):
        try:
            org_obj = Organization.objects.get(org=org_name)
        except Organization.DoesNotExist:
            return []

        return cls.objects.filter(org=org_obj)

    @classmethod
    def get_orgs_tags(cls, org_lst):
        return cls.objects.filter(org__org__in=org_lst)


class OrganizationTagOrder(models.Model):
    org = models.ForeignKey(Organization, on_delete=models.CASCADE)
    tag_name = models.CharField(max_length=255, verbose_name='Tag name')
    order_num = models.IntegerField(verbose_name='Order num')

    class Meta(object):
        ordering = ('order_num', 'tag_name')
        unique_together = (('org', 'tag_name'),)


class TagDescription(models.Model):
    tag_name = models.CharField(max_length=255, verbose_name='Tag name', unique=True)
    description = models.TextField()

    def clean(self):
        super(TagDescription, self).clean()

        self.tag_name = self.tag_name.strip()
        self.description = self.description.replace('\n', ' ').replace('\r', '')

        if self.tag_name == "":
            raise ValidationError(_("Value field is required"))

        if not all(ord(char) < 128 for char in self.tag_name):
            raise ValidationError(_("Value field contains unacceptable characters"))

    class Meta(object):
        ordering = ['tag_name']


class CourseExcludeInsights(models.Model):
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)

    class Meta(object):
        db_table = "credo_course_exclude_insights"
        verbose_name = "item exclude"
        verbose_name_plural = "items exclude insights"


class SendScores(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True)
    block_id = models.CharField(max_length=255, db_index=True)
    last_send_time = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = "credo_send_scores"
        unique_together = (('user', 'course_id', 'block_id'),)


class SendScoresMailing(models.Model):
    email_scores = models.ForeignKey(SendScores, on_delete=models.CASCADE)
    data = models.TextField(blank=True)
    last_send_time = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = "credo_send_scores_mailing"


class CopyBlockTask(TimeStampedModel, models.Model):
    NOT_STARTED = 'not_started'
    STARTED = 'started'
    FINISHED = 'finished'
    ERROR = 'error'
    STATUSES = (
        (NOT_STARTED, 'Not Started'),
        (STARTED, 'Started'),
        (FINISHED, 'Finished'),
        (ERROR, 'Error'),
    )

    task_id = models.CharField(max_length=255, db_index=True)
    block_ids = models.TextField()
    dst_location = models.CharField(max_length=255, db_index=True)
    status = models.CharField(
        max_length=255,
        choices=STATUSES,
        default=NOT_STARTED,
    )

    def set_started(self):
        self.status = self.STARTED

    def set_finished(self):
        self.status = self.FINISHED

    def set_error(self):
        self.status = self.ERROR

    def is_finished(self):
        return self.status == self.FINISHED


class SequentialViewedTask(TimeStampedModel, models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True)
    block_id = models.CharField(max_length=255, db_index=True)
    data = models.TextField(blank=True)

    class Meta(object):
        db_table = "sequential_viewed_task"


class CustomUserRole(models.Model):
    title = models.CharField(max_length=255, verbose_name='Title', unique=True)
    alias = models.SlugField(max_length=255, verbose_name='Slug', unique=True)
    course_outline_create_new_section = models.BooleanField(default=True,
                                                            verbose_name='Course Outline: Can create new Section')
    course_outline_create_new_subsection = models.BooleanField(default=True,
                                                               verbose_name='Course Outline: Can create new Subsection')
    course_outline_duplicate_section = models.BooleanField(default=True,
                                                           verbose_name='Course Outline: Can duplicate Section')
    course_outline_duplicate_subsection = models.BooleanField(default=True,
                                                              verbose_name='Course Outline: Can duplicate Subsection')
    course_outline_copy_to_other_course = models.BooleanField(default=True,
                                                              verbose_name='Course Outline: '
                                                                           'Can copy Section to other course')
    top_menu_tools = models.BooleanField(default=True, verbose_name='Top Menu: Tools Dropdown menu')
    unit_add_advanced_component = models.BooleanField(default=True,
                                                      verbose_name='Unit: Can add advanced components to a unit')
    unit_add_discussion_component = models.BooleanField(default=True,
                                                        verbose_name='Unit: Can add discussion components to a unit')
    view_tags = models.BooleanField(default=True, verbose_name='Unit: Can view tags')
    edit_library_content = models.BooleanField(default=True, verbose_name='Unit: Can Edit Library Content in Course')
    update_library_content = models.BooleanField(default=False, verbose_name='Unit: Access to "Update Now" '
                                                                             'button for Library Content')

    class Meta:
        ordering = ['title']
        verbose_name = "custom user role"
        verbose_name_plural = "custom user roles"

    def __str__(self):
        return self.title

    def to_dict(self):
        return {
            'course_outline_create_new_section': self.course_outline_create_new_section,
            'course_outline_create_new_subsection': self.course_outline_create_new_subsection,
            'course_outline_duplicate_section': self.course_outline_duplicate_section,
            'course_outline_duplicate_subsection': self.course_outline_duplicate_subsection,
            'course_outline_copy_to_other_course': self.course_outline_copy_to_other_course,
            'top_menu_tools': self.top_menu_tools,
            'unit_add_advanced_component': self.unit_add_advanced_component,
            'unit_add_discussion_component': self.unit_add_discussion_component,
            'view_tags': self.view_tags,
            'edit_library_content': self.edit_library_content,
            'update_library_content': self.update_library_content
        }


class CourseStaffExtended(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True)
    role = models.ForeignKey(CustomUserRole, on_delete=models.CASCADE)

    class Meta(object):
        unique_together = (('user', 'course_id'),)
        verbose_name = "user role"
        verbose_name_plural = "extended user roles"


class DBLogEntry(models.Model):
    event_name = models.CharField(max_length=255)
    user_id = models.IntegerField(db_index=True)
    course_id = models.CharField(max_length=255, db_index=True)
    block_id = models.CharField(max_length=255, null=True, blank=True)
    time = models.DateTimeField(auto_now_add=True, db_index=True)
    message = models.TextField()

    class Meta(object):
        db_table = "credo_tracking_logs"


class SequentialBlockAnswered(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    sequential_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    first_answered_block_id = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    user_id = models.IntegerField(db_index=True)

    class Meta(object):
        unique_together = (('sequential_id', 'user_id'),)


class SequentialBlockAttempt(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    sequential_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    user_id = models.IntegerField(db_index=True)
    dt = models.DateTimeField(db_index=True)


class OrgUsageMigration(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', unique=True)
    updated_ids = models.TextField()


class WistiaIframeMigration(models.Model):
    iframe_hash = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    wistia_video_url = models.CharField(max_length=255, db_index=True, null=True, blank=True)
    s3_video_url = models.CharField(max_length=255, null=True, blank=True)


class AttemptCourseMigration(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    done = models.BooleanField(default=False)


class AttemptUserMigration(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    sequential_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    user_id = models.IntegerField(db_index=True)


class TrackingLog(models.Model):
    course_id = models.CharField(max_length=255, null=False, db_index=True)
    org_id = models.CharField(max_length=80, null=False, db_index=True)
    course = models.CharField(max_length=255, null=False)
    run = models.CharField(max_length=80, null=False)
    term = models.CharField(max_length=20, null=True, blank=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    block_tag_id = models.CharField(max_length=80, null=True)
    user_id = models.IntegerField(db_index=True)
    is_view = models.BooleanField(default=True)
    answer_id = models.CharField(max_length=255, null=False)
    ts = models.IntegerField()
    display_name = models.CharField(max_length=2048, null=True, blank=True)
    question_name = models.CharField(max_length=2048, null=True, blank=True)
    question_hash = models.CharField(max_length=80, null=True)
    is_ora_block = models.BooleanField(default=False)
    is_ora_empty_rubrics = models.BooleanField(default=False)
    ora_criterion_name = models.CharField(max_length=255, null=True, blank=True)
    grade = models.FloatField(null=True)
    max_grade = models.FloatField(null=True)
    is_correct = models.SmallIntegerField(default=0)
    is_incorrect = models.SmallIntegerField(default=0)
    answer = models.TextField(null=True, blank=True)
    ora_answer = models.TextField(null=True, blank=True)
    correctness = models.CharField(max_length=20, null=True, blank=True)
    sequential_name = models.CharField(max_length=255, null=True)
    sequential_id = models.CharField(max_length=255, null=True, db_index=True)
    sequential_graded = models.SmallIntegerField(default=0)
    is_staff = models.SmallIntegerField(default=0)
    attempt_ts = models.IntegerField()
    is_last_attempt = models.SmallIntegerField(default=1)
    course_user_id = models.CharField(max_length=255, null=True)
    update_ts = models.IntegerField()
    update_process_num = models.IntegerField(db_index=True, null=True)

    class Meta(object):
        index_together = (('org_id', 'ts'), ('user_id', 'sequential_id'))
        unique_together = (('answer_id', 'attempt_ts'),)


class TrackingLogProp(models.Model):
    MAX_PROPS_COUNT_PER_ORG = 20

    course_user_id = models.CharField(max_length=255, null=False, db_index=True)
    org_id = models.CharField(max_length=80, null=False, db_index=True)
    course_id = models.CharField(max_length=255, null=False)
    user_id = models.IntegerField()
    update_ts = models.IntegerField(db_index=True)
    prop0 = models.CharField(max_length=255, null=True)
    prop1 = models.CharField(max_length=255, null=True)
    prop2 = models.CharField(max_length=255, null=True)
    prop3 = models.CharField(max_length=255, null=True)
    prop4 = models.CharField(max_length=255, null=True)
    prop5 = models.CharField(max_length=255, null=True)
    prop6 = models.CharField(max_length=255, null=True)
    prop7 = models.CharField(max_length=255, null=True)
    prop8 = models.CharField(max_length=255, null=True)
    prop9 = models.CharField(max_length=255, null=True)
    prop10 = models.CharField(max_length=255, null=True)
    prop11 = models.CharField(max_length=255, null=True)
    prop12 = models.CharField(max_length=255, null=True)
    prop13 = models.CharField(max_length=255, null=True)
    prop14 = models.CharField(max_length=255, null=True)
    prop15 = models.CharField(max_length=255, null=True)
    prop16 = models.CharField(max_length=255, null=True)
    prop17 = models.CharField(max_length=255, null=True)
    prop18 = models.CharField(max_length=255, null=True)
    prop19 = models.CharField(max_length=255, null=True)
    update_process_num = models.IntegerField(db_index=True, null=True)


class TrackingLogConfig(models.Model):
    key = models.CharField(max_length=255)
    value = models.CharField(max_length=255)
    updated = models.DateTimeField(auto_now=True)

    @classmethod
    def update_setting(cls, key, value):
        try:
            conf_obj = TrackingLogConfig.objects.get(key=key)
        except TrackingLogConfig.DoesNotExist:
            conf_obj = TrackingLogConfig(key=key)
        conf_obj.value = str(value)
        conf_obj.save()

    @classmethod
    def get_setting(cls, key, default_value=None):
        conf_obj = TrackingLogConfig.objects.filter(key=key).first()
        if not conf_obj:
            return default_value
        return conf_obj.value


class PropertiesInfo(models.Model):
    org = models.CharField(max_length=255, verbose_name='Org', db_index=True)
    course_id = models.CharField(max_length=255, verbose_name='Course ID', null=True)
    data = models.TextField(
        verbose_name="List of available properties",
        help_text="Config in JSON format",
    )
    update_ts = models.IntegerField(db_index=True)


class TrackingLogUserInfo(models.Model):
    org_id = models.CharField(max_length=255, db_index=True)
    user_id = models.IntegerField(db_index=True)
    email = models.CharField(max_length=255, null=True)
    full_name = models.CharField(max_length=255, null=True)
    search_token = models.CharField(max_length=255, null=True, db_index=True)

    def update_search_token(self):
        token_lst = []
        if self.email:
            token_lst.append(self.email)
        if self.full_name:
            token_lst.append(self.full_name)
        if token_lst:
            self.search_token = '|'.join(token_lst)


class TrackingLogFile(models.Model):
    log_filename = models.CharField(max_length=255, null=False, db_index=True)
    status = models.CharField(max_length=255, null=False)


class UsageLog(models.Model):
    course_id = models.CharField(max_length=255, null=False)
    org_id = models.CharField(max_length=80, null=False)
    course = models.CharField(max_length=255, null=False)
    run = models.CharField(max_length=80, null=False)
    term = models.CharField(max_length=20, null=True, blank=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    block_type = models.CharField(max_length=80, null=False)
    section_path = models.CharField(max_length=6000, null=True, blank=True)
    display_name = models.CharField(max_length=2048, null=True, blank=True)
    user_id = models.IntegerField(db_index=True)
    ts = models.IntegerField()
    is_staff = models.SmallIntegerField(default=0)
    course_user_id = models.CharField(max_length=255, null=True)
    update_ts = models.IntegerField()
    update_process_num = models.IntegerField(db_index=True, null=True)

    class Meta(object):
        index_together = (('org_id', 'ts'),)


class EnrollmentLog(models.Model):
    course_id = models.CharField(max_length=255, null=False)
    org_id = models.CharField(max_length=80, null=False)
    course = models.CharField(max_length=255, null=False)
    run = models.CharField(max_length=80, null=False)
    term = models.CharField(max_length=20, null=True, blank=True)
    user_id = models.IntegerField(db_index=True)
    ts = models.IntegerField()
    is_staff = models.SmallIntegerField(default=0)
    course_user_id = models.CharField(max_length=255, null=True)
    update_ts = models.IntegerField(db_index=True)
    update_process_num = models.IntegerField(db_index=True, null=True)

    class Meta(object):
        index_together = (('org_id', 'ts'),)
        unique_together = (('course_id', 'user_id'),)


class EnrollmentTrigger(models.Model):
    event_type = models.CharField(max_length=255, null=False)
    course_id = models.CharField(max_length=255, null=False)
    user_id = models.IntegerField(db_index=True)
    time = models.DateTimeField(auto_now_add=True, db_index=True)


class EdxApiToken(models.Model):
    title = models.CharField(max_length=255, unique=True)
    is_active = models.BooleanField(default=False)
    header_value = models.CharField(max_length=255, unique=True, default=short_token)


class RutgersCampusMapping(models.Model):
    num = models.CharField(max_length=255, null=False, db_index=True)
    school = models.CharField(max_length=255, null=False)
    campus = models.CharField(max_length=255, null=False)


class FeatureStatus(object):
    HIDDEN = 'hidden'
    BETA = 'beta'
    PUBLISHED = 'published'


class Feature(models.Model):
    INSTRUCTOR_DASHBOARD_REPORTS_DATAPICKER = 'instructor_dashboard_reports_datapicker'

    feature_name = models.CharField(max_length=255, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=(
            (FeatureStatus.HIDDEN, _('Is hidden for all')),
            (FeatureStatus.BETA, _('Published only for beta testers')),
            (FeatureStatus.PUBLISHED, _('Published for all')),
        ), default=FeatureStatus.HIDDEN,
    )

    class Meta(object):
        ordering = ['feature_name']

    def __str__(self):
        return self.feature_name

    @classmethod
    def is_published(cls, feature_name, user=None):
        f = cls.objects.filter(feature_name=feature_name).first()
        if f:
            if f.status == FeatureStatus.PUBLISHED:
                return True
            if f.status == FeatureStatus.BETA and user and FeatureBetaTester.user_is_beta_tester(f, user):
                return True
        return False


class FeatureBetaTester(models.Model):
    feature = models.ForeignKey(Feature, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)

    @classmethod
    def user_is_beta_tester(cls, feature, user):
        return cls.objects.filter(feature=feature, user=user).exists()


class OraScoreType:
    PEER = 'peer'
    SELF = 'self'
    STAFF = 'staff'


class OraBlockScore(models.Model):
    SCORE_TYPE_CHOICES = (
        (OraScoreType.PEER, OraScoreType.PEER),
        (OraScoreType.SELF, OraScoreType.SELF),
        (OraScoreType.STAFF, OraScoreType.STAFF),
    )

    course_id = models.CharField(max_length=255, null=False, db_index=True)
    org_id = models.CharField(max_length=80, null=False, db_index=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    answer = models.TextField(null=True)
    score_type = models.CharField(max_length=10, choices=SCORE_TYPE_CHOICES)
    criterion = models.CharField(max_length=255)
    option_label = models.CharField(max_length=255, null=True)
    points_possible = models.IntegerField(default=0)
    points_earned = models.IntegerField(default=0)
    created = models.DateTimeField(null=True)
    grader_id = models.IntegerField(null=True)


def usage_dt_now():
    """
    We can't use timezone.now() because we already use America/New_York timezone for usage values
    so we just replace tzinfo in the datetime object
    :return: datetime
    """
    return datetime.datetime.now().replace(tzinfo=utc)


def get_org_roles_types(org):
    roles = []
    try:
        org = Organization.objects.get(org=org)
        if org.org_type is not None:
            roles = [{
                'title': r.title,
                'id': r.id
            } for r in org.org_type.available_roles.order_by('title').all()]
    except Organization.DoesNotExist:
        pass
    roles.append({'id': 'staff', 'title': 'Staff'})
    roles.append({'id': 'instructor', 'title': 'Admin'})
    return sorted(roles, key=lambda k: k['title'])


def get_custom_user_role(course_id, user, check_enrollment=True):
    if check_enrollment:
        try:
            enrollment = CourseAccessRole.objects.get(user=user, course_id=course_id)
            if enrollment.role != 'staff':
                return None
        except CourseAccessRole.DoesNotExist:
            return None

    try:
        staff_extended = CourseStaffExtended.objects.get(user=user, course_id=course_id)
        try:
            org = Organization.objects.get(org=course_id.org)
            if org.org_type is not None:
                available_roles = [r.id for r in org.org_type.available_roles.all()]
                if staff_extended.role.id in available_roles:
                    return staff_extended.role
        except Organization.DoesNotExist:
            pass
        staff_extended.delete()
        return None
    except CourseStaffExtended.DoesNotExist:
        return None


def get_all_course_staff_extended_roles(course_id):
    staff_users = CourseStaffExtended.objects.filter(course_id=course_id)
    return {s.user_id: s.role_id for s in staff_users}


def get_extended_role_default_permissions():
    return CustomUserRole().to_dict()


def _get_sequential_parent_block(course_id, item):
    block = BlockToSequential.objects.filter(course_id=str(course_id), block_id=str(item.location)).first()
    if block:
        return block.sequential_id
    else:
        max_attempts = 10
        num_attempt = 0
        parent = item.get_parent()
        while parent and num_attempt < max_attempts:
            if parent.category == 'sequential':
                return str(parent.location)
            parent = item.get_parent()
            num_attempt = num_attempt + 1
        return None


def get_student_properties(request, course_key, item=None):
    _student_properties = getattr(request, '_student_properties', False)
    if _student_properties:
        return _student_properties

    user = request.user
    student_properties = None
    if item is None or item.category in ['course', 'chapter']:
        student_properties = get_student_properties_event_data(user, course_key)
    elif item.category == 'sequential':
        student_properties = get_student_properties_event_data(user, course_key, parent_id=str(item.location))
    else:
        seq_parent_id = _get_sequential_parent_block(str(course_key), item)
        if seq_parent_id:
            student_properties = get_student_properties_event_data(user, course_key, parent_id=seq_parent_id)

    if student_properties:
        request._student_properties = student_properties
    return student_properties


def get_student_properties_event_data(user, course_id, is_ora=False, parent_id=None, skip_user_profile=False):
    try:
        from lti_provider.models import LtiContextId
    except ImportError:
        LtiContextId = None

    result = {'registration': {}, 'enrollment': {}}
    if not skip_user_profile:
        try:
            profile = UserProfile.objects.get(user=user)
            if profile.gender:
                result['registration']['gender'] = profile.gender
        except UserProfile.DoesNotExist:
            pass

    properties = CredoStudentProperties.objects.filter(user=user)
    for prop in properties:
        if not prop.course_id:
            result['registration'][prop.name] = prop.value
        elif prop.course_id and str(course_id) == str(prop.course_id):
            result['enrollment'][prop.name] = prop.value

    try:
        profile = CredoModulesUserProfile.objects.get(user=user, course_id=course_id)
        result['enrollment'].update(profile.converted_meta())
    except CredoModulesUserProfile.DoesNotExist:
        pass

    result['enrollment']['term'] = get_custom_term()

    if parent_id and LtiContextId:
        parent_usage_key = UsageKey.from_string(parent_id)
        context = LtiContextId.objects.filter(
            course_key=course_id,
            usage_key=parent_usage_key,
            user=user).first()
        if context and context.has_properties():
            result['enrollment'].update(context.get_properties())

    if 'context_id' in result['enrollment']:
        result['enrollment'].pop('context_id', None)
    if 'lis_course_offier_sourcedid' in result['enrollment']:
        result['enrollment'].pop('lis_course_offier_sourcedid', None)

    for prop_original_name, prop_updated_name in ENROLLMENT_PROPERTIES_MAP.items():
        if prop_original_name in result['enrollment']:
            result['enrollment'][prop_updated_name] = result['enrollment'].pop(prop_original_name)

    if is_ora:
        return {'student_properties': result, 'student_id': user.id}
    else:
        return {'student_properties': result}


UNIQUE_USER_ID_COOKIE = 'credo-course-usage-id'


def get_unique_user_id(request):
    uid = request.COOKIES.get(UNIQUE_USER_ID_COOKIE, None)
    if uid:
        return str(uid)
    return None


def generate_new_user_id_cookie(request, user_id):
    request._update_unique_user_id = True
    request.COOKIES[UNIQUE_USER_ID_COOKIE] = str(uuid.uuid4()) + '_' + user_id


def update_unique_user_id_cookie(request):
    user_id = 'anon'
    if hasattr(request, 'user') and request.user.is_authenticated:
        user_id = str(request.user.id)

    course_usage_cookie_id = get_unique_user_id(request)
    if not course_usage_cookie_id:
        generate_new_user_id_cookie(request, user_id)
    else:
        cookie_arr = course_usage_cookie_id.split('_')
        if len(cookie_arr) < 2 or cookie_arr[1] != user_id:
            generate_new_user_id_cookie(request, user_id)


def get_inactive_orgs():
    deactivated_orgs_objs = EdxOrganization.objects.filter(active=False)
    return [org.name for org in deactivated_orgs_objs]


@receiver(post_save, sender=ProctoredExamStudentAttempt)
def start_new_attempt_after_exam_started(sender, instance, created, **kwargs):
    if created:
        from lms.djangoapps.courseware.tasks import track_sequential_viewed_task

        proctored_exam = instance.proctored_exam
        course_key_str = str(proctored_exam.course_id)
        usage_key_str = str(proctored_exam.content_id)

        seq_user_block = SequentialBlockAnswered(
            course_id=course_key_str,
            sequential_id=usage_key_str,
            first_answered_block_id=None,
            user_id=instance.user.id
        )
        seq_user_block.save()

        seq_block_attempt = SequentialBlockAttempt(
            course_id=course_key_str,
            sequential_id=usage_key_str,
            user_id=instance.user.id,
            dt=instance.created
        )
        seq_block_attempt.save()

        transaction.on_commit(lambda: track_sequential_viewed_task.delay(course_key_str, usage_key_str,
                                                                         instance.user.id))


@receiver(post_save, sender=CourseEnrollment)
def enrollment_trigger_after_save_course_enrollment(sender, instance, created, **kwargs):
    if created:
        course_id = str(instance.course_id)
        user_id = instance.user_id
        tr = EnrollmentTrigger(
            event_type='enrollment',
            course_id=course_id,
            user_id=user_id
        )
        tr.save()


@receiver(post_save, sender=CourseAccessRole)
def enrollment_trigger_after_save_course_access_role(sender, instance, created, **kwargs):
    user_id = instance.user_id
    course_id = str(instance.course_id)
    tr = EnrollmentTrigger(
        event_type='staff_added',
        course_id=course_id,
        user_id=user_id
    )
    tr.save()


@receiver(post_delete, sender=CourseAccessRole)
def enrollment_trigger_after_delete_course_access_role(sender, instance, **kwargs):
    user = instance.user
    course_id = str(instance.course_id)
    tr = EnrollmentTrigger(
        event_type='staff_removed',
        course_id=course_id,
        user_id=user.id
    )
    tr.save()
