import boto
import json
import hashlib
import tempfile
import subprocess
import os
from django.conf import settings
from django.core.management import BaseCommand
from django.utils.timezone import make_aware
from credo_modules.event_parser import EventProcessor
from credo_modules.models import DBLogEntry, TrackingLog, TrackingLogProp, TrackingLogFile


class Command(BaseCommand):
    EVENT_TYPES = [
        'problem_check',
        'openassessmentblock.create_submission',
        'openassessmentblock.staff_assess',
        'edx.drag_and_drop_v2.item.dropped',
        'xblock.image-explorer.hotspot.opened',
        'sequential_block.viewed',
    ]

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

    def _update_attempt(self, tr_log, is_view, attempt_json):
        if not is_view:
            if tr_log.attempts:
                tr_log.attempts = tr_log.attempts + '|' + attempt_json
            else:
                tr_log.attempts = attempt_json

    def _update_tr_log(self, tr_log, e, is_view, answer_id, real_timestamp, question_name, question_hash,
                       properties_data_json, tags_json, attempt_json):
        tr_log.course_id = e.course_id
        tr_log.org_id = e.org_id
        tr_log.course = e.course
        tr_log.run = e.run
        tr_log.prop_term = e.term
        tr_log.block_id = e.block_id
        tr_log.user_id = e.user_id
        tr_log.is_view = is_view
        tr_log.answer_id = answer_id
        tr_log.timestamp = real_timestamp
        tr_log.display_name = e.display_name
        tr_log.question_name = question_name
        tr_log.question_text = e.question_text
        tr_log.question_hash = question_hash
        tr_log.is_ora_block = e.ora_block
        tr_log.ora_criterion_name = e.criterion_name
        tr_log.is_ora_empty_rubrics = e.is_ora_empty_rubrics
        tr_log.grade = e.grade
        tr_log.max_grade = e.max_grade
        tr_log.answer = e.answers
        tr_log.correctness = e.correctness
        tr_log.is_new_attempt = e.is_new_attempt
        tr_log.properties_data = properties_data_json
        tr_log.tags = tags_json
        self._update_attempt(tr_log, is_view, attempt_json)

    def _process_existing_tr(self, e, is_view, answer_id, real_timestamp, question_name, question_hash,
                             properties_data_json, tags_json, attempt_json, db_check=True, tr_log=None):
        new_tr_props = []

        try:
            if db_check:
                tr_log = TrackingLog.objects.get(answer_id=answer_id)
            if (tr_log.is_view and not is_view) or \
                    (not tr_log.is_view and not is_view and real_timestamp > tr_log.timestamp):
                self._update_tr_log(tr_log, e, is_view, answer_id, real_timestamp, question_name, question_hash,
                                    properties_data_json, tags_json, attempt_json)
                if db_check:
                    tr_log.save()

                # update related props
                if db_check:
                    TrackingLogProp.objects.filter(answer_id=answer_id).delete()
                if e.student_properties:
                    for prop_name, prop_value in e.student_properties.items():
                        if len(prop_value) > 255:
                            prop_value = prop_value[0:255]
                        new_prop_item = TrackingLogProp(
                            answer_id=answer_id,
                            prop_name=prop_name,
                            prop_value=prop_value
                        )
                        new_tr_props.append(new_prop_item)
                    if db_check:
                        TrackingLogProp.objects.bulk_create(new_tr_props)
                        new_tr_props = []
            elif not tr_log.is_view and not is_view and real_timestamp < tr_log.timestamp:
                self._update_attempt(tr_log, is_view, attempt_json)
                if db_check:
                    tr_log.save()
            return True, tr_log, new_tr_props
        except TrackingLog.DoesNotExist:
            pass
        return False, None, []

    def _process_log(self, line, all_log_items, all_log_props_items):
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

        is_view = False
        if event_type == 'sequential_block.viewed':
            is_view = True
            block_events = DBLogEntry.objects.filter(
                user_id=res[0].user_id, course_id=res[0].course_id, block_id=res[0].block_id).values("event_name")
            block_events = list(set(block_events))
            if len(block_events) == 1 and block_events[0] == 'sequential_block.viewed':
                # continue
                pass
            else:
                return

        db_items = 0

        for e in res:
            if not e:
                continue

            answer_id = str(e.user_id) + '-' + e.block_id
            question_token = e.block_id
            question_name = e.display_name

            if e.ora_block and not e.is_ora_empty_rubrics:
                answer_id = answer_id + '-' + e.criterion_name
                question_token = e.block_id + '-' + e.criterion_name
                question_name = e.criterion_name

            answer_id = self._get_md5(answer_id)
            question_hash = self._get_md5(question_token)

            real_timestamp = make_aware(e.real_timestamp)
            properties_data_json = json.dumps(e.student_properties) if e.student_properties else None
            tags_json = json.dumps(e.saved_tags) if e.saved_tags else None
            attempt = {
                'grade': e.grade,
                'max_grade': e.max_grade,
                'answer': e.answers,
                'timestamp': e.timestamp,
                'correctness': e.correctness
            }
            attempt_json = json.dumps(attempt)

            res_db_check, _tr, _props = self._process_existing_tr(
                e, is_view, answer_id, real_timestamp, question_name,
                question_hash, properties_data_json, tags_json, attempt_json, db_check=True)
            if res_db_check:
                db_items = db_items + 1
                continue

            tr_log = all_log_items.get(answer_id)
            if tr_log:
                res_db_check, updated_tr, updated_props = self._process_existing_tr(
                    e, is_view, answer_id, real_timestamp, question_name, question_hash,
                    properties_data_json, tags_json, attempt_json, db_check=False, tr_log=tr_log)
                all_log_items[answer_id] = updated_tr
                if updated_props:
                    all_log_props_items[answer_id] = updated_props[:]
            else:
                new_item = TrackingLog()
                self._update_tr_log(new_item, e, is_view, answer_id, real_timestamp,
                                    question_name, question_hash, properties_data_json, tags_json, attempt_json)
                all_log_items[answer_id] = new_item

                if e.student_properties:
                    res_props = []
                    for prop_name, prop_value in e.student_properties.items():
                        if len(prop_value) > 255:
                            prop_value = prop_value[0:255]
                        new_prop_item = TrackingLogProp(
                            answer_id=answer_id,
                            prop_name=prop_name,
                            prop_value=prop_value
                        )
                        res_props.append(new_prop_item)
                    all_log_props_items[answer_id] = res_props[:]
        return db_items

    def handle(self, *args, **options):
        aws_access_key_id = getattr(settings, 'AWS_ACCESS_KEY_ID', None)
        aws_secret_access_key = getattr(settings, 'AWS_SECRET_ACCESS_KEY', None)

        conn = boto.connect_s3(aws_access_key_id=aws_access_key_id, aws_secret_access_key=aws_secret_access_key)
        bucket = conn.get_bucket('edu-credo-edx')

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
            all_log_props_items = {}

            print("Start process items")

            try:
                while line:
                    if line:
                        db_res = self._process_log(line, all_log_items, all_log_props_items)
                        if db_res:
                            db_updated_items = db_updated_items + db_res

                    line = fp.readline()
                    line = line.strip()

                all_log_items_lst = all_log_items.values()

                all_log_props_lst = []
                for log_props in all_log_props_items.values():
                    all_log_props_lst.extend(log_props)

                print("Updated %d existing DB records" % db_updated_items)
                print("Try to create %d tracking logs records" % len(all_log_items_lst))
                if all_log_items_lst:
                    TrackingLog.objects.bulk_create(all_log_items_lst, 1000)

                print("Try to create %d tracking log props records" % len(all_log_props_lst))
                if all_log_props_lst:
                    TrackingLogProp.objects.bulk_create(all_log_props_lst, 2000)

                fp.close()
                os.remove(log_file_name)

                self._finish_process_log(key_path)
            except Exception:
                os.remove(log_file_name)
                raise
