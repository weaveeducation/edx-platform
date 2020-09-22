import datetime
import hashlib
import json
import time
import pytz

from django.core.management import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from credo_modules.event_parser import get_timestamp_from_datetime, update_course_and_student_properties
from credo_modules.models import CourseUsageLogEntry, UsageLog, TrackingLogConfig
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructure
from student.models import CourseAccessRole
from opaque_keys.edx.keys import CourseKey


class Command(BaseCommand):
    _staff_cache = None
    _course_structure_cache = None
    update_process_num = None

    def _update_staff_cache(self, course_id):
        self._staff_cache[course_id] = []
        course_key = CourseKey.from_string(course_id)
        course_access_roles = CourseAccessRole.objects.filter(role__in=('instructor', 'staff'), course_id=course_key)
        for role in course_access_roles:
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

    def _process_log(self, log, check_existence=False, update_process_num=None):
        course_id_part = log.course_id.split(':')[1]
        org_id, course, run = course_id_part.split('+')
        json_data = json.loads(log.message)
        term = log.time.strftime("%B %Y")
        section_path = None
        display_name = None
        is_staff = False
        student_properties = self._get_student_properties(json_data.get('student_properties', {}))
        course, student_properties = update_course_and_student_properties(course, student_properties)

        if log.course_id not in self._staff_cache:
            self._update_staff_cache(log.course_id)

        if log.user_id in self._staff_cache['global'] or log.user_id in self._staff_cache[log.course_id]:
            is_staff = True

        if log.block_type != 'course':
            if log.block_id not in self._course_structure_cache:
                course_structure = ApiCourseStructure.objects.filter(block_id=log.block_id).first()
                if course_structure:
                    self._course_structure_cache[log.block_id] = [
                        course_structure.section_path,course_structure.display_name]
                    section_path = course_structure.section_path
                    display_name = course_structure.display_name
            else:
                section_path, display_name = self._course_structure_cache[log.block_id]

        if section_path or log.block_type == 'course':
            ts = get_timestamp_from_datetime(log.time)
            course_user_id_source = log.course_id + '|' + str(log.user_id)
            course_user_id = hashlib.md5(course_user_id_source.encode('utf-8')).hexdigest()
            if check_existence:
                try:
                    usage_log = UsageLog.objects.get(
                        user_id=log.user_id, ts=ts,course_id=log.course_id, block_id=log.block_id)
                    if update_process_num and usage_log.update_process_num != update_process_num:
                        usage_log.update_process_num = update_process_num
                        usage_log.save()
                    return None
                except UsageLog.DoesNotExist:
                    pass

            usage_log = UsageLog(
                course_id=log.course_id,
                org_id=org_id,
                course=course,
                run=run,
                term=term,
                block_id=log.block_id,
                block_type=log.block_type,
                section_path=section_path,
                display_name=display_name,
                user_id=log.user_id,
                ts=ts,
                is_staff=1 if is_staff else 0,
                course_user_id=course_user_id,
                update_ts=int(time.time())
            )
            return usage_log
        return None

    def handle(self, *args, **options):
        self._course_structure_cache = {}
        self._staff_cache = {
            'global': []
        }

        dt_from = TrackingLogConfig.get_setting('last_usage_log_time')
        if dt_from:
            dt_from = datetime.datetime.strptime(dt_from, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)
        else:
            dt_from = datetime.datetime(year=2019, month=12, day=9, tzinfo=pytz.UTC)

        last_usage_log = CourseUsageLogEntry.objects.all().order_by('-time').first()

        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            self._staff_cache['global'].append(superuser.id)
        process = True

        while process:
            data_to_insert = []
            dt_to = dt_from + datetime.timedelta(hours=4)
            logs = CourseUsageLogEntry.objects.filter(time__gt=dt_from, time__lte=dt_to).order_by('time')
            logs_count = len(logs)
            last_log_time = None
            print('Process Usage Log items (num: %d) from %s to %s' % (logs_count, str(dt_from), str(dt_to)))

            with transaction.atomic():
                if logs_count != 0:
                    for log in logs:
                        last_log_time = log.time
                        usage_log = self._process_log(log)
                        if usage_log:
                            data_to_insert.append(usage_log)
                    UsageLog.objects.bulk_create(data_to_insert, 1000)

                if dt_to > last_usage_log.time:
                    process = False
                dt_from = dt_from + datetime.timedelta(hours=4)

                if last_log_time:
                    TrackingLogConfig.update_setting('last_usage_log_time', last_log_time.strftime('%Y-%m-%d %H:%M:%S.%f'))

        TrackingLogConfig.update_setting('update_usage_process_num', '1')
        TrackingLogConfig.update_setting('update_usage_time', int(time.time()))
