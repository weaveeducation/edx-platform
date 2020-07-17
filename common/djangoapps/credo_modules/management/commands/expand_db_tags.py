import hashlib
import time

from django.core.management import BaseCommand
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructureTags


class Command(BaseCommand):

    def handle(self, *args, **options):
        course_overviews = CourseOverview.objects.all().order_by('id')
        for course_overview in course_overviews:
            course_id = str(course_overview.id)
            print('Start process course: %s' % course_id)

            existing_structure_tags_dict = {}
            existing_structure_tags = ApiCourseStructureTags.objects.filter(course_id=course_id)
            for tag in existing_structure_tags:
                if tag.rubric:
                    k = tag.block_id + '|' + tag.rubric
                else:
                    k = tag.block_id
                if k not in existing_structure_tags_dict:
                    existing_structure_tags_dict[k] = []
                existing_structure_tags_dict[k].append(tag.tag_name + '|' + tag.tag_value)

            tags_to_insert = []
            for tag in existing_structure_tags:
                if tag.rubric:
                    k = tag.block_id + '|' + tag.rubric
                else:
                    k = tag.block_id

                t_value = tag.tag_value.strip()
                t_value_lst = t_value.split(' - ')
                for idx, _ in enumerate(t_value_lst):
                    t_value_upd = ' - '.join(t_value_lst[0:idx + 1])
                    t_value_upd_key = tag.tag_name + '|' + t_value_upd
                    if t_value_upd_key not in existing_structure_tags_dict[k]:
                        existing_structure_tags_dict[k].append(t_value_upd_key)
                        is_parent = 1 if len(t_value_lst) > idx + 1 else 0

                        block_tag_token = tag.block_id
                        if tag.rubric:
                            block_tag_token = tag.block_id + '|' + tag.rubric
                        block_tag_id = hashlib.md5(block_tag_token.encode('utf-8')).hexdigest()

                        tags_to_insert.append(ApiCourseStructureTags(
                            org_id=tag.org_id,
                            course_id=tag.course_id,
                            block=tag.block,
                            block_tag_id=block_tag_id,
                            rubric=tag.rubric,
                            tag_name=tag.tag_name,
                            tag_value=t_value_upd,
                            is_parent=is_parent,
                            ts=int(time.time())
                        ))

            print('Try to insert %d tags: ' % len(tags_to_insert))
            if tags_to_insert:
                ApiCourseStructureTags.objects.bulk_create(tags_to_insert)
