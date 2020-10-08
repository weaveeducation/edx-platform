import datetime
import pytz
import time
import hashlib

from credo_modules.models import EnrollmentLog, EnrollmentTrigger, TrackingLogProp, TrackingLogConfig,\
    get_student_properties_event_data
from credo_modules.event_parser import update_course_and_student_properties
from credo_modules.properties_updater import PropertiesUpdater
from credo_modules.vertica import merge_data_into_vertica_table
from django.contrib.auth.models import User
from django.db.models import Q
from opaque_keys.edx.keys import CourseKey
from .process_enrollment_logs import Command as BaseProcessEnrollmentsLogsCommand


class Command(BaseProcessEnrollmentsLogsCommand):

    def handle(self, *args, **options):
        dt_from = TrackingLogConfig.get_setting('update_enrollment_time')
        if dt_from:
            dt_from = datetime.datetime.strptime(dt_from, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)
        else:
            dt_from = datetime.datetime(year=2015, month=1, day=1, tzinfo=pytz.UTC)

        self.update_process_num = int(TrackingLogConfig.get_setting('update_enrollment_process_num', 1))
        self.update_props_process_num = int(TrackingLogConfig.get_setting('update_props_process_num', 1))

        print('Update process num: %d' % self.update_process_num)
        print('Update props process num: %d' % self.update_props_process_num)

        self._staff_cache = {
            'global': []
        }

        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            self._staff_cache['global'].append(superuser.id)

        props_updater = PropertiesUpdater(show_logs=False)
        logs = EnrollmentTrigger.objects.filter(time__gt=dt_from).order_by('time')
        logs_count = len(logs)
        last_update_ts = None

        if logs_count != 0:
            print('Update properties info for courses and orgs')
            for log in logs:
                course_key = CourseKey.from_string(log.course_id)
                props_updater.update_props_for_course(course_key.org, log.course_id)

            print('Update user properties')
            props_to_insert = []

            for log in logs:
                log_prop = props_updater.update_props_for_course_and_user(
                    log.course_id, log.user_id, org_props=None, update_process_num=self.update_props_process_num)
                if log_prop:
                    props_to_insert.append(log_prop)

            if props_to_insert:
                print('Try to insert %d new props' % len(props_to_insert))
                TrackingLogProp.objects.bulk_create(props_to_insert, 1000)
            else:
                print('Nothing to insert (props)')

            print('Process %d logs' % logs_count)

            for log in logs:
                user = User.objects.get(id=log.user_id)
                course_key = CourseKey.from_string(log.course_id)
                course_id = log.course_id
                course_id_part = course_id.split(':')[1]
                org_id, course, run = course_id_part.split('+')
                user_id = log.user_id
                current_ts = int(time.time())
                enroll_log = None

                props = get_student_properties_event_data(user, course_key, skip_user_profile=True)
                student_properties = self._get_student_properties(props.get('student_properties', {}))
                course, student_properties = update_course_and_student_properties(course, student_properties)

                is_staff = False
                if course_id not in self._staff_cache:
                    self._update_staff_cache(course_id)
                if log.user_id in self._staff_cache['global'] or log.user_id in self._staff_cache[log.course_id]:
                    is_staff = True

                if log.event_type == 'enrollment':
                    term = log.time.strftime("%B %Y")
                    dt = log.time.replace(tzinfo=pytz.utc)
                    dt2 = dt - datetime.datetime(1970, 1, 1).replace(tzinfo=pytz.utc)
                    ts = int(dt2.total_seconds())
                    course_user_id_source = course_id + '|' + str(user_id)
                    course_user_id = hashlib.md5(course_user_id_source.encode('utf-8')).hexdigest()
                    enroll_log = EnrollmentLog.objects.filter(course_id=course_id, user_id=user_id).first()
                    if not enroll_log:
                        enroll_log = EnrollmentLog(
                            course_id=course_id,
                            org_id=org_id,
                            course=course,
                            run=run,
                            term=term,
                            user_id=user_id,
                            ts=ts,
                            is_staff=is_staff,
                            course_user_id=course_user_id,
                            update_ts=current_ts,
                            update_process_num=self.update_process_num
                        )
                        enroll_log.save()
                elif log.event_type in ['staff_added', 'staff_removed', 'update_props']:
                    enroll_log = EnrollmentLog.objects.filter(course_id=course_id, user_id=user_id).first()

                update = False
                if enroll_log and enroll_log.course != course:
                    enroll_log.course = course
                    update = True
                if enroll_log and enroll_log.is_staff != is_staff:
                    enroll_log.is_staff = is_staff
                    update = True
                if update:
                    enroll_log.update_process_num = self.update_process_num
                    enroll_log.update_ts = current_ts
                    enroll_log.save()

                last_update_ts = log.time.strftime('%Y-%m-%d %H:%M:%S.%f')
        else:
            print('New logs are absent')

        vertica_dsn = TrackingLogConfig.get_setting('vertica_dsn')

        print('Try to update "credo_modules_trackinglogprop" in Vertica')
        merge_data_into_vertica_table(TrackingLogProp, update_process_num=self.update_props_process_num,
                                      vertica_dsn=vertica_dsn)

        print('Try to update "credo_modules_enrollmentlog" in Vertica')
        merge_data_into_vertica_table(EnrollmentLog, update_process_num=self.update_process_num,
                                      vertica_dsn=vertica_dsn)

        new_update_process_num = self.update_process_num + 1
        new_update_props_process_num = self.update_props_process_num + 1
        print("Set new 'update_enrollment_process_num'/'update_enrollment_time' conf values: %d" % new_update_process_num)
        print("Set new 'update_props_process_num' conf values: %d" % new_update_props_process_num)
        TrackingLogConfig.update_setting('update_enrollment_process_num', new_update_process_num)
        TrackingLogConfig.update_setting('update_props_process_num', new_update_props_process_num)
        if last_update_ts:
            TrackingLogConfig.update_setting('update_enrollment_time', last_update_ts)
