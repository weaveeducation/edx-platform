import hashlib
import json
import time

from django.core.management import BaseCommand
from opaque_keys.edx.keys import CourseKey
from credo_modules.models import PropertiesInfo, TrackingLogProp, get_student_properties_event_data
from enrollment.data import get_user_enrollments


class Command(BaseCommand):

    def process_course(self, org, course_id, org_props, course_props):
        course_key = CourseKey.from_string(course_id)
        enrollments = get_user_enrollments(course_key)
        data_to_insert = []

        for enrollment in enrollments:
            user_id = enrollment.user.id
            props = get_student_properties_event_data(enrollment.user, course_key, skip_user_profile=True)
            student_properties = props['student_properties']
            course_user_id_source = str(course_id) + '|' + str(user_id)
            course_user_id = hashlib.md5(course_user_id_source.encode('utf-8')).hexdigest()

            kwargs = {
                'course_user_id': course_user_id,
                'org_id': org,
                'course_id': str(course_id),
                'user_id': user_id,
                'update_ts': int(time.time())
            }

            if len(org_props) > TrackingLogProp.MAX_PROPS_COUNT_PER_ORG:
                raise Exception('Count of props exceeds '
                                'permissible max props count: ' + TrackingLogProp.MAX_PROPS_COUNT_PER_ORG)

            for idx, org_prop in enumerate(org_props):
                prop_key = 'prop' + str(idx)
                prop_value = student_properties['enrollment'].get(org_prop, None)
                if not prop_value:
                    prop_value = student_properties['registration'].get(org_prop, None)
                if org_prop in course_props and not prop_value:
                    prop_value = '(none)'
                if len(prop_value) > 255:
                    prop_value = prop_value[0:255]
                kwargs[prop_key] = prop_value

            log_prop = TrackingLogProp(**kwargs)
            data_to_insert.append(log_prop)

        if data_to_insert:
            TrackingLogProp.objects.bulk_create(data_to_insert, 2000)
        print '------------------ Values inserted: ', len(data_to_insert)

    def handle(self, *args, **options):
        prop_org_info_lst = PropertiesInfo.objects.filter(course_id__isnull=True)
        for prop_org_info in prop_org_info_lst:
            print '--- Start process org: ', prop_org_info.org

            try:
                prop_org_info_data = json.loads(prop_org_info.data)
            except ValueError:
                prop_org_info_data = []

            if prop_org_info_data:
                prop_course_info_lst = PropertiesInfo.objects.filter(org=prop_org_info.org)\
                    .exclude(course_id__isnull=True)

                for prop_course_info in prop_course_info_lst:
                    print '--------- Start process course: ', prop_course_info.course_id
                    try:
                        prop_course_info_data = json.loads(prop_course_info.data)
                    except ValueError:
                        prop_course_info_data = []
                    self.process_course(prop_course_info.org, prop_course_info.course_id,
                                        prop_org_info_data, prop_course_info_data)
