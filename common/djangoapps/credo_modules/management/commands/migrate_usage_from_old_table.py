import hashlib
import time

from django.core.management import BaseCommand
from common.djangoapps.credo_modules.models import CourseUsage, CourseUsageLogEntry, OrgUsageMigration, UsageLog,\
    get_student_properties_event_data
from common.djangoapps.credo_modules.events_processor.utils import get_timestamp_from_datetime,\
    update_course_and_student_properties, INSIGHTS_COURSE_STAFF_ROLES, INSIGHTS_ORG_STAFF_ROLES
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructure
from common.djangoapps.student.models import CourseAccessRole
from opaque_keys.edx.keys import CourseKey


class Command(BaseCommand):
    _cache_student_properties = None
    _course_structure_cache = None
    _staff_cache = None

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

    def handle(self, *args, **options):
        self._cache_student_properties = {}
        self._course_structure_cache = {}
        self._staff_cache = {
            'global': []
        }
        first_log_entry = CourseUsageLogEntry.objects.filter(id=1).first()
        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            org_usage_obj = OrgUsageMigration.objects.filter(org=course_id).first()
            if not org_usage_obj:
                self._process_course_id(course_overview.id, first_log_entry)

    def _process_course_id(self, course_key, first_log_entry):
        course_id = str(course_key)
        print("Start process course_id: " + course_id)

        limit = 1000
        id_from = 0
        id_to = id_from + limit
        process = True

        while process:
            print("---- process course_id items: " + course_id + " (" + str(id_from) + ' - ' + str(id_to) + ")")

            usage_items = CourseUsage.objects.filter(
                course_id=course_key, first_usage_time__lt=first_log_entry.time
            ).order_by('id')[id_from:id_to]

            data_to_insert = []
            len_usage_items = len(usage_items)
            if not len_usage_items:
                process = False
            else:
                id_from = id_from + limit
                id_to = id_to + limit

                for usage_item in usage_items:

                    cnt = UsageLog.objects.filter(
                        block_id=usage_item.block_id,
                        user_id=usage_item.user.id,
                        course_id=course_id
                    ).count()

                    if cnt < usage_item.usage_count:
                        cnt_diff = usage_item.usage_count - cnt

                        if usage_item.usage_count == 1:
                            self._copy_usage(usage_item, [usage_item.last_usage_time], data_to_insert)
                        else:
                            time_lst = [usage_item.first_usage_time]
                            dt_to_append = usage_item.first_usage_time
                            cnt_diff = cnt_diff - 1

                            if usage_item.last_usage_time < first_log_entry.time and cnt_diff > 0:
                                time_lst.append(usage_item.last_usage_time)
                                dt_to_append = usage_item.last_usage_time
                                cnt_diff = cnt_diff - 1

                            if cnt_diff > 0:
                                for x in range(cnt_diff):
                                    time_lst.append(dt_to_append)
                            self._copy_usage(usage_item, time_lst, data_to_insert)

            if data_to_insert:
                UsageLog.objects.bulk_create(data_to_insert, 1000)

        org_user_migr = OrgUsageMigration(
            org=course_id
        )
        org_user_migr.save()

    def _copy_usage(self, usage_item, time_lst, data_to_insert):
        course_id = str(usage_item.course_id)
        user_id = usage_item.user.id
        cache_key = course_id + '|' + str(user_id)
        course_user_id = hashlib.md5(cache_key.encode('utf-8')).hexdigest()

        if cache_key in self._cache_student_properties:
            json_data = self._cache_student_properties[cache_key]
        else:
            json_data = get_student_properties_event_data(usage_item.user, usage_item.course_id)
            self._cache_student_properties[cache_key] = json_data

        course_id_part = course_id.split(':')[1]
        org_id, course, run = course_id_part.split('+')
        section_path = None
        display_name = None
        is_staff = False
        student_properties = self._get_student_properties(json_data.get('student_properties', {}))
        course, student_properties = update_course_and_student_properties(course, student_properties)

        if course_id not in self._staff_cache:
            self._update_staff_cache(course_id)
        if user_id in self._staff_cache['global'] or user_id in self._staff_cache[course_id]:
            is_staff = True

        if usage_item.block_type != 'course':
            if usage_item.block_id not in self._course_structure_cache:
                course_structure = ApiCourseStructure.objects.filter(block_id=usage_item.block_id).first()
                if course_structure:
                    self._course_structure_cache[usage_item.block_id] = [
                        course_structure.section_path,
                        course_structure.display_name
                    ]
                    section_path = course_structure.section_path
                    display_name = course_structure.display_name
            else:
                section_path, display_name = self._course_structure_cache[usage_item.block_id]

        if section_path or usage_item.block_type == 'course':
            for time_item in time_lst:
                term = time_item.strftime("%B %Y")
                ts = get_timestamp_from_datetime(time_item)

                usage_log = UsageLog(
                    course_id=course_id,
                    org_id=org_id,
                    course=course,
                    run=run,
                    term=term,
                    block_id=usage_item.block_id,
                    block_type=usage_item.block_type,
                    section_path=section_path,
                    display_name=display_name,
                    user_id=usage_item.user.id,
                    ts=ts,
                    is_staff=1 if is_staff else 0,
                    course_user_id=course_user_id,
                    update_ts=int(time.time())
                )
                data_to_insert.append(usage_log)
