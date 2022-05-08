import datetime
import pytz
import vertica_python

from django.core.management import BaseCommand

from lms.djangoapps.courseware.models import StudentModule
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from opaque_keys.edx.keys import CourseKey, UsageKey
from common.djangoapps.credo_modules.models import AttemptCourseMigration, TrackingLog, DBLogEntry
from common.djangoapps.credo_modules.mongo import get_course_structure
from common.djangoapps.credo_modules.vertica import get_vertica_dsn
from common.djangoapps.student.models import CourseEnrollment


class Command(BaseCommand):

    def handle(self, *args, **options):
        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            course_migration = AttemptCourseMigration.objects.filter(course_id=course_id).first()
            if course_migration and course_migration.done:
                print('Skip course: ', course_id)
                continue
            else:
                print('Process course: ', course_id)
                self._process_course(course_id)
                AttemptCourseMigration(course_id=course_id, done=True).save()
        print('DONE!')

    def _process_course(self, course_id):
        course_key = CourseKey.from_string(course_id)
        ids_to_remove = []
        db_log_to_remove_lst = []
        org_id = course_key.org
        course = course_key.course
        run = course_key.run
        course_structure = get_course_structure(course_key)
        dt_from = datetime.datetime.strptime('2019-04-01 10:50:22.468797', '%Y-%m-%d %H:%M:%S.%f')\
            .replace(tzinfo=pytz.utc)
        enrollments_fetched = False
        enrolls = []

        if course_structure:
            for block in course_structure['blocks']:
                if block['block_type'] == 'library_content':
                    library_content_block_id = 'block-v1:' + org_id + '+' + course + '+' + run + '+type@library_content+block@' + block['block_id']
                    print('------------ library_content_block_id: ', library_content_block_id)
                    block_ids = []
                    block_keys = []
                    for c in block['fields']['children']:
                        block_id = 'block-v1:' + org_id + '+' + course + '+' + run + '+type@' + c[0] + '+block@' + c[1]
                        block_ids.append(block_id)
                        block_keys.append(UsageKey.from_string(block_id))
                    if enrollments_fetched is False:
                        enrollments_fetched = True
                        enrolls = CourseEnrollment.objects.filter(
                            created__gt=dt_from,
                            course_id=course_key,
                            is_active=True)
                    num_enrolls = len(enrolls)
                    if len(enrolls):
                        en_num = 1
                        for enroll in enrolls:
                            print('Process student_id=%d: %d / %d ' % (enroll.user_id, en_num, num_enrolls))
                            en_num = en_num + 1
                            user_modules = []
                            student_modules = StudentModule.objects.filter(
                                course_id=course_key,
                                module_state_key__in=block_keys,
                                student_id=enroll.user_id).values('module_state_key')
                            for st_m in student_modules:
                                user_modules.append(str(st_m['module_state_key']))
                            blocks_absent = [block_id for block_id in block_ids if block_id not in user_modules]
                            if blocks_absent:
                                tr_logs = TrackingLog.objects.filter(
                                    org_id=org_id, user_id=enroll.user_id, block_id__in=blocks_absent,
                                    is_view=True, is_last_attempt=1).values('id')
                                if len(tr_logs):
                                    for tr_log in tr_logs:
                                        ids_to_remove.append(tr_log['id'])
                                db_log_entities = DBLogEntry.objects.filter(
                                    event_name='sequential_block.viewed',
                                    user_id=enroll.user_id,
                                    course_id=course_id,
                                    block_id__in=blocks_absent).order_by('-time').values('id', 'block_id')
                                db_log_to_remove_block_ids = []
                                for db_log_entity in db_log_entities:
                                    if db_log_entity['block_id'] not in db_log_to_remove_block_ids:
                                        db_log_to_remove_block_ids.append(db_log_entity['block_id'])
                                        db_log_to_remove_lst.append(db_log_entity['id'])

        if ids_to_remove or db_log_to_remove_lst:
            dsn = get_vertica_dsn()
            conn = vertica_python.connect(dsn=dsn)
            cursor = conn.cursor()
            limit = 1000

            print('Start remove records')
            if ids_to_remove:
                n_from = 0
                n_to = limit
                while True:
                    ids_to_remove_part = ids_to_remove[n_from:n_to]
                    if not ids_to_remove_part:
                        break
                    print('Try to remove TrackingLog items from %d to %d' % (n_from, n_to))
                    TrackingLog.objects.filter(org_id=org_id, id__in=ids_to_remove_part, is_view=True, is_last_attempt=1).delete()
                    n_from = n_from + limit
                    n_to = n_to + limit

            if db_log_to_remove_lst:
                n_from = 0
                n_to = limit
                while True:
                    db_log_to_remove_part = db_log_to_remove_lst[n_from:n_to]
                    if not db_log_to_remove_part:
                        break
                    print('Try to remove DBLogEntry items from %d to %d' % (n_from, n_to))
                    DBLogEntry.objects.filter(
                            id__in=db_log_to_remove_part, event_name='sequential_block.viewed', course_id=course_id).delete()
                    n_from = n_from + limit
                    n_to = n_to + limit

            if ids_to_remove:
                n_from = 0
                n_to = limit
                while True:
                    ids_to_remove_part = ids_to_remove[n_from:n_to]
                    if not ids_to_remove_part:
                        break
                    print('Try to remove Vertica items from %d to %d' % (n_from, n_to))
                    ids_to_remove_str = ','.join([str(id2r) for id2r in ids_to_remove_part])
                    sql = "DELETE FROM credo_modules_trackinglog " \
                          "WHERE org_id='%s' AND id in (%s) AND is_view=1 AND is_last_attempt=1"\
                          % (org_id, ids_to_remove_str)
                    cursor.execute(sql)
                    cursor.execute("COMMIT")
                    n_from = n_from + limit
                    n_to = n_to + limit
            print('Finish remove records')
