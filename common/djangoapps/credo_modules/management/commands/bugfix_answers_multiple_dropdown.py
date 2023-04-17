import datetime
import json
import pytz

from django.core.management import BaseCommand
from django.core.cache import caches
from common.djangoapps.credo_modules.models import DBLogEntry, TrackingLog, TrackingLogConfig
from common.djangoapps.credo_modules.events_processor import EventProcessor
from common.djangoapps.credo_modules.vertica import merge_data_into_vertica_table


class Command(BaseCommand):

    def handle(self, *args, **options):
        cache = caches['default']
        cache_key = 'bugfix_answers_multiple_dropdown'
        cached_dt = cache.get(cache_key)
        update_process_num = 5
        items_to_update = 1000

        dt_to_max = TrackingLogConfig.get_setting('last_log_time')
        if dt_to_max:
            dt_to_max = datetime.datetime.strptime(dt_to_max, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)

        if cached_dt:
            dt_from = datetime.datetime.strptime(cached_dt, '%Y-%m-%d %H:%M:%S.%f').replace(tzinfo=pytz.utc)
        else:
            dt_from = datetime.datetime(year=2020, month=1, day=1, tzinfo=pytz.UTC)

        num_to_update = TrackingLog.objects.filter(update_process_num=update_process_num).count()
        process = True
        while process:
            dt_to = dt_from + datetime.timedelta(hours=4)
            if dt_to > dt_to_max:
                process = False
            else:
                print('Process DBLogEntry items from %s to %s: ' % (str(dt_from), str(dt_to)))
                logs = DBLogEntry.objects.filter(
                    time__gt=dt_from, time__lte=dt_to, event_name='problem_check').order_by('time')
                for log in logs:
                    event = json.loads(log.message)
                    submissions_count = len(event['event'].get('submission', {}))
                    if submissions_count > 1:
                        res_list = EventProcessor.process(log.event_name, event)
                        e = res_list[0]
                        try:
                            tr = TrackingLog.objects.get(answer_id=e.answer_id, ts=e.dtime_ts)
                            if tr.answer != e.answers:
                                tr.answer = e.answers
                                tr.update_process_num = update_process_num
                                tr.save()
                                num_to_update = num_to_update + 1
                        except TrackingLog.DoesNotExist:
                            print('----------- TrackingLog not found: answer_id=%s, ts=%s'
                                  % (str(e.answer_id), str(e.dtime_ts)))

                cache.set(cache_key, dt_to.strftime('%Y-%m-%d %H:%M:%S.%f'), 60 * 60 * 12)
                print('num_to_update: ', str(num_to_update))
                if num_to_update >= items_to_update:
                    merge_data_into_vertica_table(TrackingLog, update_process_num=update_process_num)
                    num_to_update = 0
                    TrackingLog.objects.filter(update_process_num=update_process_num).update(update_process_num=1)
                dt_from = dt_from + datetime.timedelta(hours=4)

        if num_to_update > 0:
            merge_data_into_vertica_table(TrackingLog, update_process_num=update_process_num)
            TrackingLog.objects.filter(update_process_num=update_process_num).update(update_process_num=1)

        print('DONE!')
