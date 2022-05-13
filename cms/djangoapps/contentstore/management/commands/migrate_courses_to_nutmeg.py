from django.core.management.base import BaseCommand

from xmodule.modulestore.django import modulestore

from cms.djangoapps.contentstore.tasks import update_outline_from_modulestore_task


class Command(BaseCommand):

    def handle(self, *args, **options):
        for course in modulestore().get_course_summaries():
            update_outline_from_modulestore_task.delay(str(course.id))
