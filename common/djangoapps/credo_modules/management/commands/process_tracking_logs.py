import boto
import datetime
import json
import hashlib
import tempfile
import time
import subprocess
import pytz
import os
from django.conf import settings
from django.core.management import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Q
from credo_modules.event_parser import EventProcessor, prepare_text_for_column_db
from credo_modules.models import DBLogEntry, TrackingLog, TrackingLogUserInfo, TrackingLogFile, TrackingLogConfig,\
    SequentialBlockAttempt
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from student.models import CourseAccessRole
from opaque_keys.edx.keys import CourseKey


class Command(BaseCommand):
    EVENT_TYPES = [
        'problem_check',
        'openassessmentblock.create_submission',
        'openassessmentblock.staff_assess',
        'edx.drag_and_drop_v2.item.dropped',
        'xblock.image-explorer.hotspot.opened',
        'sequential_block.viewed',
    ]
    update_process_num = None
    _updated_user_attempts = None
    _last_attempt_dt = None
    _user_attempts_cache = None

    def _get_attempts_info(self, answer_ts, user_id, sequential_id):
        if not self._last_attempt_dt:
            seq_block_attempt = SequentialBlockAttempt.objects.filter().order_by('-dt').first()
            self._last_attempt_dt = seq_block_attempt.dt
            self._user_attempts_cache = {}

        if not sequential_id or answer_ts < 1562025600:  # i.e answer_ts < '2019-07-02'
            return None, True, []

        key = sequential_id + '|' + str(user_id)
        if key not in self._user_attempts_cache:
            self._user_attempts_cache[key] = []
            user_attempts = []
            attempts = SequentialBlockAttempt.objects.filter(sequential_id=sequential_id, user_id=user_id,
                                                             dt__lte=self._last_attempt_dt).order_by('dt')
            if attempts:
                for attempt in attempts:
                    dt = attempt.dt.replace(tzinfo=pytz.utc)
                    dt2 = dt - datetime.datetime(1970, 1, 1).replace(tzinfo=pytz.utc)
                    t = int(dt2.total_seconds())
                    user_attempts.append(t)
                    self._user_attempts_cache[key].append(t)
        else:
            user_attempts = self._user_attempts_cache[key]

        attempts_num = len(user_attempts)
        if attempts_num == 0:
            return 0, True, []

        for i, attempt_ts in enumerate(user_attempts):
            if (i + 1) == attempts_num:
                return attempt_ts, True, user_attempts
            elif attempt_ts <= answer_ts < user_attempts[i + 1]:
                return attempt_ts, False, user_attempts
        return 0, True, user_attempts

    def _start_process_log(self, log_path):
        try:
            tr = TrackingLogFile.objects.get(log_filename=log_path)
            if tr.status == 'started':
                return True
            elif tr.status == 'finished':
                return False
        except TrackingLogFile.DoesNotExist:
            tr = TrackingLogFile(
                log_filename=log_path,
                status='started'
            )
            tr.save()
            return True

    def _finish_process_log(self, log_path):
        tr = TrackingLogFile.objects.get(log_filename=log_path)
        tr.status = 'finished'
        tr.save()

    def _get_md5(self, val):
        return hashlib.md5(val.encode('utf-8')).hexdigest()

    def _update_b2s_cache(self, course_id, b2s_cache):
        b2s_items = BlockToSequential.objects.filter(course_id=course_id)
        b2s_cache[course_id] = {}
        for b2s_item in b2s_items:
            b2s_cache[course_id][b2s_item.block_id] = (b2s_item.sequential_id, b2s_item.sequential_name,
                                                       b2s_item.graded, b2s_item.visible_to_staff_only)

    def _update_staff_cache(self, course_id, staff_cache):
        staff_cache[course_id] = []
        course_key = CourseKey.from_string(course_id)
        course_access_roles = CourseAccessRole.objects.filter(role__in=('instructor', 'staff'), course_id=course_key)
        for role in course_access_roles:
            staff_cache[course_id].append(role.user_id)

    def _update_user_info(self, org_id, user_id, prop_email, prop_full_name, users_processed_cache):
        token = org_id + '|' + str(user_id)
        create_new = False

        if token in users_processed_cache:
            log_user_info = users_processed_cache[token]
        else:
            try:
                log_user_info = TrackingLogUserInfo.objects.get(org_id=org_id, user_id=user_id)
                users_processed_cache[token] = log_user_info
            except TrackingLogUserInfo.DoesNotExist:
                log_user_info = TrackingLogUserInfo(org_id=org_id, user_id=user_id)
                create_new = True

        email_to_set = ''
        full_name_to_set = ''

        if create_new:
            try:
                user = User.objects.get(id=user_id)
                email_to_set = user.email
                if user.first_name and user.last_name:
                    full_name_to_set = user.first_name + ' ' + user.last_name
                elif user.first_name and not user.last_name:
                    full_name_to_set = user.first_name
                elif not user.first_name and user.last_name:
                    full_name_to_set = user.last_name
            except User.DoesNotExist:
                pass

        if prop_email:
            email_to_set = prop_email
        if prop_full_name:
            full_name_to_set = prop_full_name

        changed = False
        if email_to_set and log_user_info.email != email_to_set:
            log_user_info.email = email_to_set
            changed = True
        if full_name_to_set and log_user_info.full_name != full_name_to_set:
            log_user_info.full_name = full_name_to_set
            changed = True

        if create_new or changed:
            log_user_info.update_search_token()
            log_user_info.save()
            if create_new:
                users_processed_cache[token] = log_user_info

    def _update_tr_log(self, tr_log, e, is_view, answer_id, real_timestamp, attempt_ts, is_last_attempt):
        tr_log.course_id = e.course_id
        tr_log.org_id = e.org_id
        tr_log.course = e.course
        tr_log.run = e.run
        tr_log.term = e.term
        tr_log.block_id = e.block_id
        tr_log.user_id = e.user_id
        tr_log.is_view = is_view
        tr_log.answer_id = answer_id
        tr_log.ts = real_timestamp
        tr_log.display_name = e.display_name
        tr_log.question_name = e.question_name
        tr_log.question_hash = e.question_hash
        tr_log.is_ora_block = e.ora_block
        tr_log.ora_criterion_name = e.criterion_name
        tr_log.is_ora_empty_rubrics = e.is_ora_empty_rubrics
        tr_log.ora_answer = e.ora_user_answer
        tr_log.grade = e.grade
        tr_log.max_grade = e.max_grade
        tr_log.answer = e.answers
        tr_log.answer_hash = e.answers_hash
        tr_log.correctness = e.correctness
        if e.ora_block and not e.is_ora_empty_rubrics:
            tr_log.is_correct = 0
            tr_log.is_incorrect = 0
        else:
            tr_log.is_correct = 1 if e.is_correct else 0
            tr_log.is_incorrect = 0 if e.is_correct else 1
        tr_log.sequential_name = prepare_text_for_column_db(e.sequential_name)
        tr_log.sequential_id = e.sequential_id
        tr_log.sequential_graded = 1 if e.sequential_graded else 0
        tr_log.is_staff = 1 if e.is_staff else 0
        tr_log.attempt_ts = attempt_ts
        tr_log.is_last_attempt = 1 if is_last_attempt else 0
        tr_log.course_user_id = e.course_user_id
        tr_log.update_ts = int(time.time())
        tr_log.update_process_num = self.update_process_num

    def _tr_log_need_update(self, tr_log, is_view, real_timestamp):
        if (tr_log.is_view and not is_view) or (not tr_log.is_view and not is_view and real_timestamp > tr_log.ts):
            return True
        return False

    def _process_existing_tr(self, e, is_view, answer_id, real_timestamp, attempt_ts, is_last_attempt, db_check=True,
                             tr_log=None):
        if db_check:
            try:
                tr_log = TrackingLog.objects.get(answer_id=answer_id, attempt_ts=attempt_ts)
                if self._tr_log_need_update(tr_log, is_view, real_timestamp):
                    self._update_tr_log(tr_log, e, is_view, answer_id, real_timestamp, attempt_ts, is_last_attempt)
                    tr_log.save()
                return True, tr_log
            except TrackingLog.DoesNotExist:
                pass
            return False, None
        else:
            if self._tr_log_need_update(tr_log, is_view, real_timestamp):
                self._update_tr_log(tr_log, e, is_view, answer_id, real_timestamp, attempt_ts, is_last_attempt)
            return True, tr_log

    def _check_sequential_block_viewed(self, res):
        update_attempts_strategy_dt = datetime.datetime(2020, 2, 10, 3, 40, 12, 0)
        if res[0].dtime > update_attempts_strategy_dt:  # process all viewed events after attempts bugfix
            return True

        block_events_data = DBLogEntry.objects.filter(
            user_id=res[0].user_id, course_id=res[0].course_id, block_id=res[0].block_id).values("event_name")
        block_events = [b['event_name'] for b in block_events_data]
        block_events = list(set(block_events))

        if len(block_events) == 1 and block_events[0] == 'sequential_block.viewed':
            # continue
            return True
        else:
            # skip "empty" attempts in case if
            # there are some answers or 'sequential_block.remove_view' events
            return False

    def _update_previous_attempts(self, user_id, sequential_id, last_attempt_ts):
        key = sequential_id + '|' + str(user_id)
        if self._updated_user_attempts is None:
            self._updated_user_attempts = {}
        if key not in self._updated_user_attempts or self._updated_user_attempts[key] != last_attempt_ts:
            TrackingLog.objects.filter(
                user_id=user_id, sequential_id=sequential_id, is_last_attempt=1
            ).exclude(
                attempt_ts=last_attempt_ts
            ).update(
                is_last_attempt=0,
                update_process_num=self.update_process_num
            )
            self._updated_user_attempts[key] = last_attempt_ts

    def _process_log(self, line, all_log_items, b2s_cache, staff_cache, users_processed_cache):
        line = line.strip()

        try:
            event = json.loads(line)
        except ValueError:
            return

        event_type = event.get('event_type')

        if event.get('event_source') != 'server' or event_type not in self.EVENT_TYPES:
            return

        try:
            res = EventProcessor.process(event_type, event)
            if not res:
                return
        except Exception:
            if event_type == 'edx.drag_and_drop_v2.item.dropped':
                return
            else:
                raise

        is_view = False
        if event_type == 'sequential_block.viewed':
            is_view = True
            view_process = self._check_sequential_block_viewed(res)
            if not view_process:
                return

        db_items = 0

        for e in res:
            if not e:
                continue

            course_id = e.course_id
            if course_id not in b2s_cache:
                self._update_b2s_cache(course_id, b2s_cache)

            if course_id not in staff_cache:
                self._update_staff_cache(course_id, staff_cache)

            sequential_id, sequential_name, sequential_graded, visible_to_staff_only = None, None, False, False
            if e.block_id in b2s_cache[course_id]:
                sequential_id, sequential_name, sequential_graded, visible_to_staff_only = b2s_cache[course_id][e.block_id]

            e.sequential_name = sequential_name
            e.sequential_id = sequential_id
            e.sequential_graded = sequential_graded

            if e.user_id in staff_cache['global'] or e.user_id in staff_cache[course_id]:
                e.is_staff = True

            if is_view and visible_to_staff_only and not e.is_staff:
                return

            self._update_user_info(e.org_id, e.user_id, e.prop_user_email, e.prop_user_name, users_processed_cache)

            question_token = e.question_name
            if sequential_name:
                question_token = sequential_name + '|' + e.question_name
            e.question_hash = self._get_md5(question_token)
            e.answers_hash = self._get_md5(question_token + '|' + e.answers)

            real_timestamp = e.dtime_ts

            if sequential_id:
                attempt_ts, is_last_attempt, user_attempts = self._get_attempts_info(
                    real_timestamp, e.user_id, sequential_id)
                if len(user_attempts) > 1 and is_last_attempt:
                    self._update_previous_attempts(e.user_id, sequential_id, user_attempts[-1])
            else:
                attempt_ts = 0
                is_last_attempt = True

            res_db_check, _tr = self._process_existing_tr(
                e, is_view, e.answer_id, real_timestamp, attempt_ts, is_last_attempt, db_check=True)
            if res_db_check:
                db_items = db_items + 1
                continue

            log_item_key = e.answer_id + '|' + str(attempt_ts)

            tr_log = all_log_items.get(log_item_key)
            if tr_log:
                res_db_check, updated_tr = self._process_existing_tr(
                    e, is_view, e.answer_id, real_timestamp, attempt_ts, is_last_attempt, db_check=False, tr_log=tr_log)
                all_log_items[log_item_key] = updated_tr
            else:
                new_item = TrackingLog()
                self._update_tr_log(new_item, e, is_view, e.answer_id, real_timestamp, attempt_ts, is_last_attempt)
                all_log_items[log_item_key] = new_item

        return db_items

    def handle(self, *args, **options):
        aws_access_key_id = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        aws_secret_access_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)

        conn = boto.connect_s3(aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)
        bucket = conn.get_bucket('edu-credo-edx')

        b2s_cache = {}
        staff_cache = {
            'global': []
        }
        users_processed_cache = {}

        superusers = User.objects.filter(Q(is_staff=True) | Q(is_superuser=True))
        for superuser in superusers:
            staff_cache['global'].append(superuser.id)

        print("Prepare keys")
        all_keys = []
        bucket_items = bucket.list(prefix='data')
        key_num = 0
        for key in bucket_items:
            if key.key.endswith('.gz'):
                all_keys.append(key)
                key_num = key_num + 1
                if key_num % 1000 == 0:
                    print("processed %d keys" % key_num)

        keys = [k.key for k in sorted(all_keys, key=lambda x: x.last_modified)]
        files_num = len(keys)
        last_line = None

        for file_num, key_path in enumerate(keys):
            print('------------------------------------------------')
            print("Process file %d / %d: %s" % (file_num + 1, files_num, key_path))
            res = self._start_process_log(key_path)
            if not res:
                print("Skip log file")
                continue

            key = bucket.get_key(key_path)

            tf = tempfile.NamedTemporaryFile(delete=False, suffix='.log.gz')
            print("Download gz file " + tf.name)
            key.get_contents_to_file(tf)
            tf.close()

            log_file_name = tf.name[:-3]

            print("Unzip " + tf.name)
            subprocess.call(["gunzip", tf.name], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            fp = open(log_file_name, 'r')
            line = fp.readline()
            line = line.strip()

            db_updated_items = 0
            all_log_items = {}

            print("Start process items")

            try:
                while line:
                    if line:
                        last_line = line
                        db_res = self._process_log(line, all_log_items, b2s_cache, staff_cache,
                                                   users_processed_cache)
                        if db_res:
                            db_updated_items = db_updated_items + db_res

                    line = fp.readline()
                    line = line.strip()

                all_log_items_lst = all_log_items.values()

                print("Updated %d existing DB records" % db_updated_items)
                print("Try to create %d tracking logs records" % len(all_log_items_lst))
                if all_log_items_lst:
                    TrackingLog.objects.bulk_create(all_log_items_lst, 1000)

                fp.close()
                os.remove(log_file_name)

                self._finish_process_log(key_path)
            except Exception:
                os.remove(log_file_name)
                raise

            if file_num + 1 == files_num:
                line_json = json.loads(last_line)
                event_time = line_json.get('time').split('+')[0].replace('T', ' ')
                TrackingLogConfig.update_setting('last_log_time', event_time)
                TrackingLogConfig.update_setting('update_process_num', '1')
                TrackingLogConfig.update_setting('update_time', int(time.time()))
