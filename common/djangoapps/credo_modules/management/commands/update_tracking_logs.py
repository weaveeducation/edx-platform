import datetime

from .process_tracking_logs import Command as BaseProcessLogsCommand
from credo_modules.models import DBLogEntry, TrackingLog, TrackingLogProp, TrackingLogConfig
from credo_modules.properties_updater import PropertiesUpdater
from credo_modules.vertica import merge_data_into_vertica_table
from django.contrib.auth.models import User
from django.db.models import Q
from opaque_keys.edx.keys import CourseKey


class Command(BaseProcessLogsCommand):

    def handle(self, *args, **options):
        conf_obj1 = TrackingLogConfig.objects.filter(key='last_log_time').first()
        if not conf_obj1:
            conf_obj1 = TrackingLogConfig(
                key='last_log_time'
            )
            dt_from = datetime.datetime(year=2015, month=1, day=1)
        else:
            dt_from = datetime.datetime.strptime(conf_obj1.value, '%Y-%m-%d %H:%M:%S.%f')

        conf_obj2 = TrackingLogConfig.objects.filter(key='update_process_num').first()
        if not conf_obj2:
            conf_obj2 = TrackingLogConfig(
                key='update_process_num',
                value='1'
            )
            self.update_process_num = 1
        else:
            self.update_process_num = int(conf_obj2.value)

        b2s_cache = {}
        staff_cache = {
            'global': []
        }
        users_processed_cache = []
        db_updated_items = 0
        all_log_items = {}

        print('Prepare super users data')
        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            staff_cache['global'].append(superuser.id)

        print('Fetch all DBLogEntry items to process')
        logs = DBLogEntry.objects.filter(time__gt=dt_from).order_by('time')
        logs_count = len(logs)

        props_updater = PropertiesUpdater()

        print('Update properties info for courses and orgs')
        for log in logs:
            course_key = CourseKey.from_string(log.course_id)
            props_updater.update_props_for_course(course_key.org, log.course_id)

        print('Update user properties')
        props_to_insert = []

        for log in logs:
            log_prop = props_updater.update_props_for_course_and_user(
                log.course_id, log.user_id, org_props=None, course_props=None,
                update_process_num=self.update_process_num)
            if log_prop:
                props_to_insert.append(log_prop)

        if props_to_insert:
            print('Try to insert %d new props' % len(props_to_insert))
            TrackingLogProp.objects.bulk_create(props_to_insert, 1000)

            print('Try to update "credo_modules_trackinglogprop" in Vertica')
            merge_data_into_vertica_table('credo_modules_trackinglogprop', TrackingLogProp, self.update_process_num)
        else:
            print('Nothing to insert (props)')

        print('Process %d logs' % logs_count)

        if logs:
            for log in logs:
                db_res = self._process_log(log.message, all_log_items, b2s_cache, staff_cache,
                                           users_processed_cache)
                if db_res:
                    db_updated_items = db_updated_items + db_res

            all_log_items_lst = all_log_items.values()
            if all_log_items_lst:
                print('Try to insert %d new log items' % len(all_log_items_lst))
                TrackingLog.objects.bulk_create(all_log_items_lst, 1000)
            else:
                print('Nothing to insert (log items)')

            print('Try to update "credo_modules_trackinglog" in Vertica')
            merge_data_into_vertica_table('credo_modules_trackinglog', TrackingLog, self.update_process_num)

            print("Update last_log_time conf value")
            conf_obj1.value = str(logs[-1].time)
            conf_obj1.save()
        else:
            print("There is no new logs")

        print("Update update_process_num conf value")
        conf_obj2.value = self.update_process_num + 1
        conf_obj2.save()
