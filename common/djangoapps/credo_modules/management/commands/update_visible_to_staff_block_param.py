from django.core.management import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.models import BlockToSequential
from credo_modules.models import TrackingLog
from credo_modules.mongo import get_course_structure
from opaque_keys.edx.keys import CourseKey
from courseware.utils import CREDO_GRADED_ITEM_CATEGORIES


class Command(BaseCommand):

    def handle(self, *args, **options):
        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            course_key = CourseKey.from_string(course_id)
            course_structure = get_course_structure(course_key)
            if not course_structure:
                continue

            print('Process course: ', course_id)

            course_id_part = course_id.split(':')[1]

            seq_is_hidden = []
            vertical_is_hidden = []
            library_content_is_hidden = []
            item_is_hidden = []

            for block in course_structure['blocks']:
                if block['block_type'] == 'chapter':
                    visible_to_staff_only = block.get('fields', {}).get('visible_to_staff_only', False)
                    if visible_to_staff_only:
                        children = block.get('fields', {}).get('children', [])
                        for child in children:
                            seq_is_hidden.append(child[1])

            for block in course_structure['blocks']:
                if block['block_type'] == 'sequential' and block['block_id'] in seq_is_hidden:
                    children = block.get('fields', {}).get('children', [])
                    for child in children:
                        vertical_is_hidden.append(child[1])

            for block in course_structure['blocks']:
                if block['block_type'] == 'vertical':
                    visible_to_staff_only = block.get('fields', {}).get('visible_to_staff_only', False)
                    if visible_to_staff_only or block['block_id'] in vertical_is_hidden:
                        children = block.get('fields', {}).get('children', [])
                        for child in children:
                            if child[0] == 'library_content':
                                library_content_is_hidden.append(child[1])
                            elif child[0] in CREDO_GRADED_ITEM_CATEGORIES:
                                block_id = 'block-v1:' + course_id_part + '+type@' + child[0] + '+block@' + child[1]
                                item_is_hidden.append(block_id)

            for block in course_structure['blocks']:
                if block['block_type'] == 'library_content' and block['block_id'] in library_content_is_hidden:
                    children = block.get('fields', {}).get('children', [])
                    for child in children:
                        if child[0] in CREDO_GRADED_ITEM_CATEGORIES:
                            block_id = 'block-v1:' + course_id_part + '+type@' + child[0] + '+block@' + child[1]
                            if block_id not in item_is_hidden:
                                item_is_hidden.append(block_id)

            for item_id in item_is_hidden:
                print('Try to update: ', item_id)
                BlockToSequential.objects.filter(block_id=item_id).update(visible_to_staff_only=True)
                TrackingLog.objects.filter(block_id=item_id, is_view=True, is_staff=0).delete()
