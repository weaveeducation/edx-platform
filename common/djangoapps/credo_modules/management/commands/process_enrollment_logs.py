import datetime
import hashlib
import time
import pytz

from django.core.management import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from common.djangoapps.credo_modules.events_processor.utils import get_timestamp_from_datetime,\
    update_course_and_student_properties, INSIGHTS_COURSE_STAFF_ROLES, INSIGHTS_ORG_STAFF_ROLES
from common.djangoapps.credo_modules.models import EnrollmentLog, TrackingLogConfig, get_student_properties_event_data
from common.djangoapps.student.models import CourseAccessRole, CourseEnrollment
from opaque_keys.edx.keys import CourseKey


User = get_user_model()


class Command(BaseCommand):
    _staff_cache = None
    _course_structure_cache = None
    update_props_process_num = None

    def _update_staff_cache(self, course_id):
        self._staff_cache[course_id] = []
        course_key = CourseKey.from_string(course_id)

        course_access_roles = CourseAccessRole.objects.filter(
            role__in=INSIGHTS_COURSE_STAFF_ROLES, course_id=course_key)
        for role in course_access_roles:
            self._staff_cache[course_id].append(role.user_id)

        org_access_roles = CourseAccessRole.objects.filter(
            role__in=INSIGHTS_ORG_STAFF_ROLES, org=course_key.org)
        for role in org_access_roles:
            if not role.course_id:
                self._staff_cache[course_id].append(role.user_id)

    def _get_student_properties(self, student_properties):
        result = {}
        tmp_result = {}
        types = ['registration', 'enrollment']
        for tp in types:
            tmp_result.update(student_properties.get(tp, {}))
        for prop_key, prop_value in tmp_result.items():
            prop_value = prop_value.strip()
            if prop_value:
                if len(prop_value) > 255:
                    prop_value = prop_value[0:255]
            result[prop_key.lower()] = prop_value
        return result

    def _process_log(self, log, update_time):
        course_id = str(log.course.id)
        user_id = log.user.id
        course_id_part = course_id.split(':')[1]
        org_id, course, run = course_id_part.split('+')
        props = get_student_properties_event_data(log.user, log.course.id, skip_user_profile=True)
        term = log.created.strftime("%B %Y")
        is_staff = False
        student_properties = self._get_student_properties(props.get('student_properties', {}))
        course, student_properties = update_course_and_student_properties(course, student_properties)

        if course_id not in self._staff_cache:
            self._update_staff_cache(course_id)

        if user_id in self._staff_cache['global'] or user_id in self._staff_cache[course_id]:
            is_staff = True

        ts = get_timestamp_from_datetime(log.created)
        course_user_id_source = course_id + '|' + str(user_id)
        course_user_id = hashlib.md5(course_user_id_source.encode('utf-8')).hexdigest()
        try:
            EnrollmentLog.objects.get(course_id=course_id, user_id=user_id)
            return None
        except EnrollmentLog.DoesNotExist:
            enrollment_log = EnrollmentLog(
                course_id=course_id,
                org_id=org_id,
                course=course,
                run=run,
                term=term,
                user_id=user_id,
                ts=ts,
                is_staff=1 if is_staff else 0,
                course_user_id=course_user_id,
                update_ts=update_time
            )
            return enrollment_log

    def handle(self, *args, **options):
        current_update_time = int(time.time())
        self._staff_cache = {
            'global': []
        }

        dt_from = datetime.datetime(year=2015, month=12, day=21, tzinfo=pytz.UTC)
        last_enroll_log = CourseEnrollment.objects.all().order_by('-created').first()
        update_time = int(time.time())

        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            self._staff_cache['global'].append(superuser.id)
        process = True

        while process:
            data_to_insert = []
            dt_to = dt_from + datetime.timedelta(hours=4)
            logs = CourseEnrollment.objects.filter(created__gt=dt_from, created__lte=dt_to).order_by('created')
            logs_count = len(logs)
            print('Process Enrollments items (num: %d) from %s to %s' % (logs_count, str(dt_from), str(dt_to)))

            with transaction.atomic():
                if logs_count != 0:
                    for log in logs:
                        usage_log = self._process_log(log, update_time)
                        if usage_log:
                            data_to_insert.append(usage_log)
                    EnrollmentLog.objects.bulk_create(data_to_insert, 1000)

                if dt_to > last_enroll_log.created:
                    process = False
                dt_from = dt_from + datetime.timedelta(hours=4)

        TrackingLogConfig.update_setting('update_enrollment_process_num', '1')
        TrackingLogConfig.update_setting(
            'last_enrollment_log_time', last_enroll_log.created.strftime('%Y-%m-%d %H:%M:%S.%f'))
        TrackingLogConfig.update_setting('update_enrollment_time', current_update_time)
