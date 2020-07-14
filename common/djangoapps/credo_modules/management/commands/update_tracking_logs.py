import datetime
import time
import pytz

from .process_tracking_logs import Command as BaseProcessLogsCommand
from credo_modules.models import DBLogEntry, TrackingLog, TrackingLogProp, TrackingLogConfig
from credo_modules.properties_updater import PropertiesUpdater
from credo_modules.vertica import merge_data_into_vertica_table
from django.contrib.auth.models import User
from django.db.models import Q
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructureTags, ApiCourseStructureUpdateTime


class Command(BaseProcessLogsCommand):

    def handle(self, *args, **options):
        dt_from = TrackingLogConfig.get_setting('last_log_time')
        if dt_from:
            dt_from = datetime.datetime.strptime(dt_from, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)
        else:
            dt_from = datetime.datetime(year=2015, month=1, day=1, tzinfo=pytz.UTC)

        self.update_process_num = int(TrackingLogConfig.get_setting('update_process_num', 1))
        print('Update process num: %d' % self.update_process_num)

        b2s_cache = {}
        staff_cache = {
            'global': []
        }
        users_processed_cache = {}
        course_ids_lst = []
        db_updated_items = 0

        print('Prepare super users data')
        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            staff_cache['global'].append(superuser.id)

        process = True
        new_last_log_time = None
        props_updater = PropertiesUpdater(show_logs=False)

        while process:
            dt_to = dt_from + datetime.timedelta(hours=4)
            print('Process DBLogEntry items from %s to %s: ' % (str(dt_from), str(dt_to)))
            logs = DBLogEntry.objects.filter(time__gt=dt_from, time__lte=dt_to).order_by('time')
            logs_count = len(logs)

            if logs_count != 0:
                print('Update properties info for courses and orgs')
                for log in logs:
                    if log.course_id not in course_ids_lst:
                        course_ids_lst.append(log.course_id)
                    course_key = CourseKey.from_string(log.course_id)
                    props_updater.update_props_for_course(course_key.org, log.course_id)

                print('Update user properties')
                props_to_insert = []
                all_log_items = {}

                for log in logs:
                    log_prop = props_updater.update_props_for_course_and_user(
                        log.course_id, log.user_id, org_props=None, course_props=None,
                        update_process_num=self.update_process_num)
                    if log_prop:
                        props_to_insert.append(log_prop)

                if props_to_insert:
                    print('Try to insert %d new props' % len(props_to_insert))
                    TrackingLogProp.objects.bulk_create(props_to_insert, 1000)
                else:
                    print('Nothing to insert (props)')

                print('Process %d logs' % logs_count)

                for log in logs:
                    db_res = self._process_log(log.message, all_log_items, b2s_cache, staff_cache,
                                               users_processed_cache)
                    if db_res:
                        db_updated_items = db_updated_items + db_res
                    new_last_log_time = log.time

                all_log_items_lst = all_log_items.values()
                if all_log_items_lst:
                    print('Try to insert %d new log items' % len(all_log_items_lst))
                    TrackingLog.objects.bulk_create(all_log_items_lst, 1000)
                else:
                    print('Nothing to insert (log items)')

                dt_from = dt_from + datetime.timedelta(hours=4)
            else:
                print('New logs are absent')
                process = False

        vertica_dsn = TrackingLogConfig.get_setting('vertica_dsn')

        print('Try to update "credo_modules_trackinglogprop" in Vertica')
        merge_data_into_vertica_table(TrackingLogProp, update_process_num=self.update_process_num,
                                      vertica_dsn=vertica_dsn)

        print('Try to update "credo_modules_trackinglog" in Vertica')
        merge_data_into_vertica_table(TrackingLog, update_process_num=self.update_process_num,
                                      vertica_dsn=vertica_dsn)

        print('Try to update "api_course_structure_tags" in Vertica')
        if course_ids_lst:
            course_id_to_upd_obj = {}
            course_ids_relevant_lst = []

            for course_id in course_ids_lst:
                try:
                    course_upd_time_obj = ApiCourseStructureUpdateTime.objects.get(course_id=course_id)
                    if not course_upd_time_obj.processed:
                        course_id_to_upd_obj[course_id] = course_upd_time_obj
                        course_ids_relevant_lst.append(course_id)
                except ApiCourseStructureUpdateTime.DoesNotExist:
                    course_id_to_upd_obj[course_id] = ApiCourseStructureUpdateTime(
                        course_id=course_id,
                        processed=False
                    )
                    course_ids_relevant_lst.append(course_id)

            if course_ids_relevant_lst:
                print('course_ids_relevant_lst: %s' % str(course_ids_relevant_lst))

                merge_data_into_vertica_table(ApiCourseStructureTags, course_ids_lst=course_ids_relevant_lst,
                                              vertica_dsn=vertica_dsn)
                for course_id, course_upd_time_obj in course_id_to_upd_obj.items():
                    course_upd_time_obj.processed = True
                    course_upd_time_obj.save()
            else:
                print('course_ids_relevant_lst list is empty')
        else:
            print('course_ids_lst list is empty')

        if new_last_log_time:
            print("Set 'last_log_time' conf value: %s" % new_last_log_time.strftime('%Y-%m-%d %H:%M:%S.%f'))
            TrackingLogConfig.update_setting('last_log_time', new_last_log_time.strftime('%Y-%m-%d %H:%M:%S.%f'))

        new_update_process_num = self.update_process_num + 1
        print("Set new 'update_process_num'/'update_time' conf values: %d" % new_update_process_num)
        TrackingLogConfig.update_setting('update_process_num', new_update_process_num)
        TrackingLogConfig.update_setting('update_time', int(time.time()))
