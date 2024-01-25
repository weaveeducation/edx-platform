import datetime
import time
import pytz

from .process_tracking_logs import Command as BaseProcessLogsCommand
from common.djangoapps.credo_modules.models import DBLogEntry, TrackingLog, TrackingLogProp, TrackingLogConfig
from common.djangoapps.credo_modules.properties_updater import PropertiesUpdater
from common.djangoapps.credo_modules.vertica import merge_data_into_vertica_table
from django.contrib.auth import get_user_model
from django.db.models import Q
from opaque_keys.edx.keys import CourseKey
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructureTags
from lms.djangoapps.courseware.utils import CREDO_GRADED_ITEM_CATEGORIES


User = get_user_model()


class Command(BaseProcessLogsCommand):

    update_props_process_num = None

    def handle(self, *args, **options):
        def filter_api_tag_helper(api_tag_item, api_tags_fields):
            block_id_idx = api_tags_fields.index('block_id')
            block_id_val = api_tag_item[block_id_idx]
            block_type_val = block_id_val.split('@')[1].split('+')[0]
            if block_type_val not in CREDO_GRADED_ITEM_CATEGORIES:
                return True
            return False

        current_update_time = int(time.time())
        dt_from = TrackingLogConfig.get_setting('last_log_time')
        if dt_from:
            dt_from = datetime.datetime.strptime(dt_from, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)
        else:
            dt_from = datetime.datetime(year=2015, month=1, day=1, tzinfo=pytz.UTC)

        self.update_process_num = int(TrackingLogConfig.get_setting('update_process_num', 1))
        self.update_props_process_num = int(TrackingLogConfig.get_setting('update_props_process_num', 1))
        last_update_time = int(TrackingLogConfig.get_setting('update_time', 0))

        print('Update process num: %d' % self.update_process_num)
        print('Update props process num: %d' % self.update_props_process_num)

        b2s_cache = {}
        staff_cache = {
            'global': []
        }
        users_processed_cache = {}
        db_updated_items = 0

        print('Prepare super users data')
        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            staff_cache['global'].append(superuser.id)

        process = True
        new_last_log_time = None
        props_updater = PropertiesUpdater(show_logs=False)
        time_interval = 31  # days

        while process:
            dt_to = dt_from + datetime.timedelta(days=time_interval)
            print('Process DBLogEntry items from %s to %s: ' % (str(dt_from), str(dt_to)))
            logs = DBLogEntry.objects.filter(time__gt=dt_from, time__lte=dt_to).order_by('time')
            logs_count = len(logs)

            if logs_count != 0:
                print('Update properties info for courses and orgs')
                for log in logs:
                    course_key = CourseKey.from_string(log.course_id)
                    props_updater.update_props_for_course(course_key.org, log.course_id)

                print('Update user properties')
                props_to_insert = []
                all_log_items = {}

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

                dt_from = dt_from + datetime.timedelta(days=time_interval)
            else:
                print('New logs are absent')
                process = False

        vertica_dsn = TrackingLogConfig.get_setting('vertica_dsn')

        print('Try to update "credo_modules_trackinglogprop" in Vertica')
        merge_data_into_vertica_table(TrackingLogProp, update_process_num=self.update_props_process_num,
                                      vertica_dsn=vertica_dsn)

        print('Try to update "credo_modules_trackinglog" in Vertica')
        try:
            merge_data_into_vertica_table(TrackingLog, update_process_num=self.update_process_num,
                                          vertica_dsn=vertica_dsn)
        except Exception as e:
            print('Error during merge data into vertica table: %s' % str(e))

        print('Try to update "api_course_structure_tags" in Vertica')
        course_ids_lst = []
        tags_courses = ApiCourseStructureTags.objects.filter(ts__gt=last_update_time)\
            .values('course_id').distinct()
        for tag_course_item in tags_courses:
            course_ids_lst.append(tag_course_item['course_id'])

        if course_ids_lst:
            print('Checking tags for course_ids_lst: %s' % str(course_ids_lst))

            # merge into vertica using 5 courses only
            ci = 0
            courses_num = 5

            while True:
                course_ids_from = ci * courses_num
                course_ids_to = ci * courses_num + courses_num
                course_ids_tmp_lst = course_ids_lst[course_ids_from: course_ids_to]
                if course_ids_tmp_lst:
                    merge_data_into_vertica_table(ApiCourseStructureTags, course_ids_lst=course_ids_tmp_lst,
                                                  vertica_dsn=vertica_dsn, filter_fn=filter_api_tag_helper)
                    ci = ci + 1
                else:
                    break
        else:
            print('course_ids_lst list is empty')

        if new_last_log_time:
            print("Set 'last_log_time' conf value: %s" % new_last_log_time.strftime('%Y-%m-%d %H:%M:%S.%f'))
            TrackingLogConfig.update_setting('last_log_time', new_last_log_time.strftime('%Y-%m-%d %H:%M:%S.%f'))

        new_update_process_num = self.update_process_num + 1
        new_update_props_process_num = self.update_props_process_num + 1
        print("Set new 'update_process_num'/'update_time' conf values: %d" % new_update_process_num)
        print("Set new 'update_props_process_num' conf values: %d" % new_update_props_process_num)
        TrackingLogConfig.update_setting('update_process_num', new_update_process_num)
        TrackingLogConfig.update_setting('update_props_process_num', new_update_props_process_num)
        TrackingLogConfig.update_setting('update_time', current_update_time)
