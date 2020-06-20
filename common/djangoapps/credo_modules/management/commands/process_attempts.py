import datetime
import json

from django.db import transaction
from django.core.management import BaseCommand
from django.utils.timezone import make_aware
from django.utils import timezone
from credo_modules.models import DBLogEntry, SequentialBlockAttempt
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from edx_proctoring.models import ProctoredExam, ProctoredExamStudentAttempt


class Command(BaseCommand):

    event_types = [
        'problem_check',
        'openassessmentblock.create_submission',
        'openassessmentblock.staff_assess',
        'edx.drag_and_drop_v2.item.dropped',
        'xblock.image-explorer.hotspot.opened',
    ]

    def _get_sequential_id(self, block_id, block_seq_cache):
        if block_id in block_seq_cache:
            return block_seq_cache[block_id]
        try:
            b2s = BlockToSequential.objects.get(block_id=block_id)
            block_seq_cache[block_id] = b2s.sequential_id
            return b2s.sequential_id
        except BlockToSequential.DoesNotExist:
            return None

    def handle(self, *args, **options):
        processed_data = []
        block_seq_cache = {}

        date_from = make_aware(datetime.datetime.strptime('2019-09-16', '%Y-%m-%d'), timezone.utc)

        limit = 1000
        page = 0
        process = True

        while process:
            events_from = page * limit
            events_to = events_from + limit
            page = page + 1
            print '------ Process items from %d to %d' % (events_from, events_to)

            events = DBLogEntry.objects.filter(time__gte=date_from).order_by('time')
            events_data = events[events_from:events_to]
            if not events_data:
                return

            update_time = None

            for event in events_data:
                block_id = event.block_id
                user_id = event.user_id

                if not update_time:
                    print '----- Process events from %s' % str(event.time)

                if event.event_name not in self.event_types:
                    continue

                sequential_id = self._get_sequential_id(block_id, block_seq_cache)
                if not sequential_id:
                    continue

                seq_user_id = sequential_id + '|' + str(user_id)
                if seq_user_id in processed_data:
                    continue

                user_attempt = SequentialBlockAttempt.objects.filter(sequential_id=sequential_id, user_id=user_id)\
                    .first()
                if user_attempt:
                    continue

                with transaction.atomic():
                    self._process_user_and_sequential_block(user_id, sequential_id)
                processed_data.append(seq_user_id)

    def _process_user_and_sequential_block(self, user_id, sequential_id):
        try:
            proctored_exam = ProctoredExam.objects.get(content_id=sequential_id)

            attempts = ProctoredExamStudentAttempt.objects.filter(proctored_exam=proctored_exam, user_id=user_id)\
                .order_by('created')
            for attempt in attempts:
                seq_attempt = SequentialBlockAttempt(
                    course_id=proctored_exam.course_id,
                    sequential_id=sequential_id,
                    user_id=user_id,
                    dt=attempt.created
                )
                seq_attempt.save()
            return
        except ProctoredExam.DoesNotExist:
            pass

        blocks_to_attempt = {}
        b2s_items = BlockToSequential.objects.filter(sequential_id=sequential_id)
        b2s_items_list = [b2s.block_id for b2s in b2s_items]

        log_items = DBLogEntry.objects.filter(
            user_id=user_id, block_id__in=b2s_items_list, event_name__in=self.event_types).order_by('time')
        for log_item in log_items:
            attempt_num = 1
            if log_item.event_name == 'problem_check':
                json_data = json.loads(log_item.message)
                attempt_num = json_data.get('event', {}).get('attempts', 1)
            elif log_item.event_name in ('openassessmentblock.create_submission', 'openassessmentblock.staff_assess'):
                attempt_num = 1
            elif log_item.event_name == 'edx.drag_and_drop_v2.item.dropped':
                json_data = json.loads(log_item.message)
                attempt_num = len(json_data.get('event', {}).get('item_state', []))
            elif log_item.event_name == 'xblock.image-explorer.hotspot.opened':
                attempt_num = len(json_data.get('event', {}).get('opened_hotspots', []))

            last_attempt_num = blocks_to_attempt.get(log_item.block_id, None)
            if not blocks_to_attempt or (last_attempt_num is not None and attempt_num <= last_attempt_num):
                created = log_item.time - datetime.timedelta(seconds=60)
                seq_attempt = SequentialBlockAttempt(
                    course_id=log_item.course_id,
                    sequential_id=sequential_id,
                    user_id=user_id,
                    dt=created
                )
                seq_attempt.save()
                blocks_to_attempt[log_item.block_id] = attempt_num
