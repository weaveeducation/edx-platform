import copy
import hashlib

from django.core.cache import caches
from django.core.management import BaseCommand
from django.conf import settings
from pymongo import MongoClient
from pymongo.database import Database
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.credo_modules.mongo import get_course_structure
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.tasks import update_course_structure


class Command(BaseCommand):

    def get_block_id(self, block, mongo_conn):
        definitions = mongo_conn.modulestore.definitions
        display_name = block.get('fields', {}).get('display_name')
        if not display_name:
            if block['block_type'] == 'openassessment':
                display_name = 'Open Response Assessment'
            else:
                return None
        definition_obj = definitions.find_one({'_id': block['definition']})
        if definition_obj:
            if definition_obj['block_type'] == 'problem':
                data = definition_obj.get('fields', {}).get('data', None)
                if data:
                    return hashlib.md5(data.encode('utf-8')).hexdigest()
            if definition_obj['block_type'] == 'openassessment':
                prompt = definition_obj.get('fields', {}).get('prompt', None)
                if prompt:
                    prompt = prompt + '|' + display_name
                    return hashlib.md5(prompt.encode('utf-8')).hexdigest()
        return None

    def handle(self, *args, **options):
        source_course_ids = [
            'course-v1:NimblyWise+Assessment-Master+02',
            'course-v1:NimblyWise+Dev-03+2019',
            'course-v1:NimblyWise+Dev-02+2019',
            'course-v1:NimblyWise+Dev-03+2020',
            'course-v1:NimblyWise+Dev-02+2020',
            'course-v1:NimblyWise+Dev-01+2019'
        ]
        source_data_dict = {}

        orgs_to_update = [
            'Virginia-State-University',
            'William-Jewell-College',
            'Winston-Salem-State-University'
        ]

        connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                                 port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
        mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
        mongo_conn.authenticate(settings.CONTENTSTORE['DOC_STORE_CONFIG']['user'],
                                settings.CONTENTSTORE['DOC_STORE_CONFIG']['password'])

        for source_course_id in source_course_ids:
            source_course_data = get_course_structure(CourseKey.from_string(source_course_id))
            if not source_course_data:
                continue
            for block in source_course_data['blocks']:
                if block['block_type'] in ("problem", "openassessment") and block['asides']:
                    block_id = self.get_block_id(block, mongo_conn)
                    if block_id:
                        for aside in block['asides']:
                            if (block['block_type'] == 'problem' and aside['aside_type'] == 'tagging_aside') or\
                              (block['block_type'] == 'openassessment' and aside['aside_type'] == 'tagging_ora_aside'):
                                saved_tags = aside.get('fields', {}).get('saved_tags', {})
                                if saved_tags:
                                    source_data_dict[block_id] = copy.deepcopy(saved_tags)

        for org_num, org in enumerate(orgs_to_update):
            print('-- Start process org: ', org_num, org)
            courses = CourseOverview.objects.filter(org=org)
            for c in courses:
                if str(c.id) not in source_course_ids:
                    print('----- Start process course: ', str(c.id))
                    self._update_course_with_tags(mongo_conn, c.id, source_data_dict)

    def _update_course_with_tags(self, mongo_conn, course_key, source_data_dict):
        cache = caches['course_structure_cache']
        active_versions = mongo_conn.modulestore.active_versions
        structures = mongo_conn.modulestore.structures

        course = active_versions.find_one({
            'org': course_key.org,
            'course': course_key.course,
            'run': course_key.run
        })
        if not course:
            return None

        for version_name, version_id in course['versions'].items():
            version_obj = structures.find_one({'_id': version_id})
            changed = False
            for i, block in enumerate(version_obj['blocks']):
                block_id = self.get_block_id(block, mongo_conn)
                if block_id and block_id in source_data_dict and 'asides' in block:
                    for j, aside in enumerate(block['asides']):
                        if block['block_type'] == 'problem' and aside['aside_type'] == 'tagging_aside':
                            for tag_type, tag_vals in source_data_dict[block_id].items():
                                if tag_type not in block['asides'][j]['fields']['saved_tags']:
                                    version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][tag_type] = tag_vals[:]
                                    changed = True
                                else:
                                    for tag_val in tag_vals:
                                        if isinstance(version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][tag_type], str):
                                            tmp_val = version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][tag_type]
                                            version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][tag_type] = [tmp_val]
                                        if tag_val not in version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][tag_type]:
                                            version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][tag_type].append(tag_val)
                                            changed = True
                        if block['block_type'] == 'openassessment' and aside['aside_type'] == 'tagging_ora_aside':
                            for ora_rubric, ora_tag_info in source_data_dict[block_id].items():
                                if ora_rubric not in block['asides'][j]['fields']['saved_tags']:
                                    version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][ora_rubric] = copy.deepcopy(ora_tag_info)
                                    changed = True
                                else:
                                    for tag_type, tag_vals in source_data_dict[block_id][ora_rubric].items():
                                        if tag_type not in block['asides'][j]['fields']['saved_tags'][ora_rubric]:
                                            version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][ora_rubric][tag_type] = tag_vals[:]
                                            changed = True
                                        else:
                                            for tag_val in tag_vals:
                                                if tag_val not in version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][ora_rubric][tag_type]:
                                                    version_obj['blocks'][i]['asides'][j]['fields']['saved_tags'][ora_rubric][tag_type].append(tag_val)
                                                    changed = True
            if changed:
                print('Save!')
                structures.save(version_obj)
                cached_version = cache.get(str(version_obj['_id']))
                if cached_version:
                    print('remove cache for: ', str(version_obj['_id']))
                    cache.delete(str(version_obj['_id']))
                update_course_structure(str(course_key))
