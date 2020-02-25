import datetime
import json

from django.db import transaction
from django.db.models import Q
from django.core.management import BaseCommand
from django.utils.timezone import make_aware
from credo_modules.models import CourseUsage, CourseUsageLogEntry, OrgUsageMigration, get_student_properties_event_data
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview


class Command(BaseCommand):
    """
    Examples:
        ./manage.py lms migrate_usage_for_org org1 org2 --date_from=2019-09-01

    """

    _cache_student_properties = {}

    def add_arguments(self, parser):
        parser.add_argument('--date_from', help='Specifies datetime in format YYYY-MM-DD')
        parser.add_argument('--org', help='Org name')

    def handle(self, *args, **options):
        org = options.get('org')
        if not org:
            raise Exception('Please provide org name')

        first_new_usage = CourseUsageLogEntry.objects.all().order_by('time').first()
        date_from = options.get('date_from')
        if not date_from:
            date_from = '2019-09-01'
        date_from = make_aware(datetime.datetime.strptime(date_from, '%Y-%m-%d'))

        self._process_org(org, date_from, first_new_usage.time)

    def _process_org(self, org, first_dt, last_dt):
        print "Start process org: ", org
#        org_usage_migration = OrgUsageMigration.objects.filter(org=org).first()
        updated_ids = []
#        if not org_usage_migration:
#            org_usage_migration = OrgUsageMigration(
#                org=org,
#            )
#        if org_usage_migration.updated_ids:
#            updated_ids = json.loads(org_usage_migration.updated_ids)

        course_ids = []
        courses = CourseOverview.objects.filter(org=org)
        for c in courses:
            course_ids.append(c.id)

        usage_items = CourseUsage.objects.filter(course_id__in=course_ids)\
            .filter(Q(first_usage_time__gte=first_dt, first_usage_time__lt=last_dt)
                    | Q(last_usage_time__gte=first_dt, last_usage_time__lt=last_dt))\
            .order_by('first_usage_time', 'last_usage_time', 'user_id')

        len_usage_items = len(usage_items)
        i = 0

        for usage_item in usage_items:
            i = i + 1

            if usage_item.id not in updated_ids:
                print "Process usage item [id=%d] num %d / %d" % (usage_item.id, i, len_usage_items)
            else:
                print "Process usage item [id=%d] num %d / %d - Skip" % (usage_item.id, i, len_usage_items)
                continue

            with transaction.atomic():
                if usage_item.usage_count == 1\
                  or usage_item.first_usage_time < first_dt\
                  or usage_item.last_usage_time > last_dt:
                    if usage_item.first_usage_time < first_dt:
                        self._copy_usage(usage_item, [usage_item.last_usage_time])
                    else:
                        self._copy_usage(usage_item, [usage_item.first_usage_time])
                else:
                    time_lst = [usage_item.first_usage_time, usage_item.last_usage_time]
                    if usage_item.usage_count > 2:
                        for x in range(usage_item.usage_count - 2):
                            time_lst.append(usage_item.last_usage_time)
                    self._copy_usage(usage_item, time_lst)

                updated_ids.append(usage_item.id)
#                org_usage_migration.updated_ids = json.dumps(updated_ids)
#                org_usage_migration.save()

    def _copy_usage(self, usage_item, time_lst):
        cache_key = str(usage_item.course_id) + '|' + str(usage_item.user.id)
        if cache_key in self._cache_student_properties:
            student_properties = self._cache_student_properties[cache_key]
        else:
            student_properties = get_student_properties_event_data(usage_item.user, usage_item.course_id)
            self._cache_student_properties[cache_key] = student_properties

        message = json.dumps(student_properties if student_properties else {})
        for time_item in time_lst:
            new_item = CourseUsageLogEntry(
                user_id=usage_item.user.id,
                course_id=str(usage_item.course_id),
                block_id=usage_item.block_id,
                block_type=usage_item.block_type,
                time=time_item,
                message=message
            )
            new_item.save()
