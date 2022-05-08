import datetime
import time
import pytz

from .process_usage_logs import Command as BaseProcessUsageLogsCommand
from common.djangoapps.credo_modules.models import CourseUsageLogEntry, UsageLog, TrackingLogProp, TrackingLogConfig
from common.djangoapps.credo_modules.properties_updater import PropertiesUpdater
from common.djangoapps.credo_modules.vertica import merge_data_into_vertica_table
from django.contrib.auth import get_user_model
from django.db.models import Q
from opaque_keys.edx.keys import CourseKey


User = get_user_model()


class Command(BaseProcessUsageLogsCommand):

    def handle(self, *args, **options):
        current_update_time = int(time.time())
        dt_from = TrackingLogConfig.get_setting('last_usage_log_time')
        if dt_from:
            dt_from = datetime.datetime.strptime(dt_from, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)
        else:
            dt_from = datetime.datetime(year=2017, month=1, day=1, tzinfo=pytz.UTC)

        self.update_process_num = int(TrackingLogConfig.get_setting('update_usage_process_num', 1))
        self.update_props_process_num = int(TrackingLogConfig.get_setting('update_props_process_num', 1))

        print('Update process num: %d' % self.update_process_num)
        print('Update props process num: %d' % self.update_props_process_num)

        self._course_structure_cache = {}
        self._staff_cache = {
            'global': []
        }

        vertica_dsn = TrackingLogConfig.get_setting('vertica_dsn')

        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            self._staff_cache['global'].append(superuser.id)

        process = True
        new_last_log_time = None
        props_updater = PropertiesUpdater(show_logs=False)
        time_interval = 7  # days

        while process:
            dt_to = dt_from + datetime.timedelta(days=time_interval)
            print('Process CourseUsageLogEntry items from %s to %s: ' % (str(dt_from), str(dt_to)))
            logs = CourseUsageLogEntry.objects.filter(time__gt=dt_from, time__lte=dt_to).order_by('time')
            logs_count = len(logs)
            data_to_insert = []

            if logs_count != 0:
                print('Update properties info for courses and orgs')
                for log in logs:
                    course_key = CourseKey.from_string(log.course_id)
                    props_updater.update_props_for_course(course_key.org, log.course_id)

                print('Update user properties')
                props_to_insert = []

                for log in logs:
                    log_prop = props_updater.update_props_for_course_and_user(
                        log.course_id, log.user_id, org_props=None, update_tracking_log_user_info=True,
                        update_process_num=self.update_props_process_num)
                    if log_prop:
                        props_to_insert.append(log_prop)

                if props_to_insert:
                    print('Try to insert %d new props' % len(props_to_insert))
                    TrackingLogProp.objects.bulk_create(props_to_insert, 1000)
                else:
                    print('Nothing to insert (props)')

                print('Process %d logs' % logs_count)

                for log in logs:
                    db_res = self._process_log(log, update_process_num=self.update_process_num)
                    if db_res:
                        data_to_insert.append(db_res)
                    new_last_log_time = log.time

                if data_to_insert:
                    print('Try to insert %d new log items' % len(data_to_insert))
                    UsageLog.objects.bulk_create(data_to_insert, 1000)
                else:
                    print('Nothing to insert (log items)')

                print('Try to update "credo_modules_usagelog" in Vertica')
                merge_data_into_vertica_table(UsageLog, update_process_num=self.update_process_num,
                                              vertica_dsn=vertica_dsn, skip_delete_step=True, delimiter='$')

                if new_last_log_time:
                    print("Set 'last_usage_log_time' conf value: %s" % new_last_log_time.strftime(
                        '%Y-%m-%d %H:%M:%S.%f'))
                    TrackingLogConfig.update_setting('last_usage_log_time',
                                                     new_last_log_time.strftime('%Y-%m-%d %H:%M:%S.%f'))

                self.update_process_num = self.update_process_num + 1
                print("Set new 'update_usage_process_num'/'update_usage_time' conf values: %d / %d"
                      % (self.update_process_num, current_update_time))
                TrackingLogConfig.update_setting('update_usage_process_num', self.update_process_num)
                TrackingLogConfig.update_setting('update_usage_time', current_update_time)

                dt_from = dt_from + datetime.timedelta(days=time_interval)
            else:
                print('New logs are absent')
                process = False

        print('Try to update "credo_modules_trackinglogprop" in Vertica')
        merge_data_into_vertica_table(TrackingLogProp, update_process_num=self.update_props_process_num,
                                      vertica_dsn=vertica_dsn)

        new_update_props_process_num = self.update_props_process_num + 1
        print("Set new 'update_props_process_num' conf values: %d" % new_update_props_process_num)
        TrackingLogConfig.update_setting('update_props_process_num', new_update_props_process_num)
