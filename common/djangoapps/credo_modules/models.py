import logging
import time
import datetime
import json
import re
import uuid
from urlparse import urlparse
from django.dispatch import receiver
from django.contrib.auth.models import User
from django.db import models, IntegrityError, OperationalError, transaction
from django.db.models import F
from opaque_keys.edx.django.models import CourseKeyField
from opaque_keys.edx.keys import CourseKey, UsageKey
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.utils.timezone import utc
from model_utils.models import TimeStampedModel

from student.models import CourseEnrollment, CourseAccessRole, ENROLL_STATUS_CHANGE, EnrollStatusChange, UserProfile
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential


log = logging.getLogger("course_usage")


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
            for k, v in enrollment_properties.iteritems():
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
    CredoStudentProperties.objects.filter(course_id=course_id, user=user).delete()
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

    user = models.ForeignKey(User)
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
            except OperationalError, e:
                if current_attempt < max_attempts:
                    current_attempt += 1
                    time.sleep(3)
                else:
                    log.error('Failed to save course usage: ' + str(e))
                    return

    return func_wrapper


class CourseUsage(models.Model):
    """
    Deprecated model
    """
    MODULE_TYPES = (('problem', 'problem'),
                    ('video', 'video'),
                    ('html', 'html'),
                    ('course', 'course'),
                    ('chapter', 'Section'),
                    ('sequential', 'Subsection'),
                    ('vertical', 'Vertical'),
                    ('library_content', 'Library Content'))

    user = models.ForeignKey(User)
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
                    #cls._update_block_usage(course_key, request.user.id,
                    #                        block_type, block_id, unique_user_id)
                    pass
            cls.mark_viewed(request, block_id)


class CourseUsageLogEntry(models.Model):
    user_id = models.IntegerField(db_index=True)
    course_id = models.CharField(max_length=255, db_index=True)
    block_id = models.CharField(max_length=255, null=True, blank=True)
    block_type = models.CharField(max_length=32, null=True, blank=True)
    time = models.DateTimeField(auto_now_add=True, db_index=True)
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
            message=message
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

    class Meta:
        ordering = ['title']

    def __unicode__(self):
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
            'exclude_properties': self.get_exclude_properties(),
        }

    @property
    def is_carousel_view(self):
        if self.org_type is not None:
            return self.org_type.enable_new_carousel_view
        else:
            return False


class OrganizationTag(models.Model):
    org = models.ForeignKey(Organization)
    tag_name = models.CharField(max_length=255, verbose_name='Tag name')
    insights_view = models.BooleanField(default=True, verbose_name='Display on the Insights')
    progress_view = models.BooleanField(default=True, verbose_name='Display on the My Skills page')

    class Meta(object):
        ordering = ('org', 'tag_name')
        unique_together = (('org', 'tag_name'),)


class CourseExcludeInsights(models.Model):
    user = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    course_id = CourseKeyField(max_length=255, db_index=True, null=True, blank=True)

    class Meta(object):
        db_table = "credo_course_exclude_insights"
        verbose_name = "item exclude"
        verbose_name_plural = "items exclude insights"


class SendScores(models.Model):
    user = models.ForeignKey(User)
    course_id = CourseKeyField(max_length=255, db_index=True)
    block_id = models.CharField(max_length=255, db_index=True)
    last_send_time = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = "credo_send_scores"
        unique_together = (('user', 'course_id', 'block_id'),)


class SendScoresMailing(models.Model):
    email_scores = models.ForeignKey(SendScores)
    data = models.TextField(blank=True)
    last_send_time = models.DateTimeField(null=True, blank=True)

    class Meta(object):
        db_table = "credo_send_scores_mailing"


class CopySectionTask(TimeStampedModel, models.Model):
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
    block_id = models.CharField(max_length=255)
    source_course_id = CourseKeyField(max_length=255, db_index=True)
    dst_course_id = CourseKeyField(max_length=255)
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

    class Meta(object):
        db_table = "copy_section_task"
        unique_together = (('task_id', 'block_id', 'dst_course_id'),)


class SequentialViewedTask(TimeStampedModel, models.Model):
    user = models.ForeignKey(User)
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
#    rerun_course = models.BooleanField(default=True, verbose_name='Studio Home Page: Can re-run a course')
#    create_new_course = models.BooleanField(default=True, verbose_name='Studio Home Page: Can create new course')
#    view_archived_courses = models.BooleanField(default=True,
#                                                verbose_name='Studio Home Page: Can view archived courses')
#    create_new_library = models.BooleanField(default=True, verbose_name='Studio Home Page: Can create new library')
#    view_libraries = models.BooleanField(default=True, verbose_name='Studio Home Page: Can view libraries')

    class Meta:
        ordering = ['title']
        verbose_name = "custom user role"
        verbose_name_plural = "custom user roles"

    def __unicode__(self):
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
    user = models.ForeignKey(User)
    course_id = CourseKeyField(max_length=255, db_index=True)
    role = models.ForeignKey(CustomUserRole)

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


def get_student_properties_event_data(user, course_id, is_ora=False, parent_id=None):
    try:
        from lti_provider.models import LtiContextId
    except ImportError:
        LtiContextId = None

    result = {'registration': {}, 'enrollment': {}}
    profile = UserProfile.objects.get(user=user)
    if profile.gender:
        result['registration']['gender'] = profile.gender

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
        return unicode(uid)
    return None


def generate_new_user_id_cookie(request, user_id):
    request._update_unique_user_id = True
    request.COOKIES[UNIQUE_USER_ID_COOKIE] = unicode(uuid.uuid4()) + '_' + user_id


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
