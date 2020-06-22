import copy
import hashlib

from django.core.cache import caches
from django.core.management import BaseCommand
from django.conf import settings
from pymongo import MongoClient
from pymongo.database import Database
from opaque_keys.edx.keys import CourseKey
from credo_modules.mongo import get_course_structure
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from openedx.core.djangoapps.content.block_structure.tasks import update_course_structure


class Command(BaseCommand):

    def get_block_id(self, block, mongo_conn):
        definitions = mongo_conn.modulestore.definitions
        display_name = block.get('fields', {}).get('display_name')
        if not display_name:
            return
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
        source_course_id = 'course-v1:Virginia-State-University+LO-02+Spring-2017'
        source_data_dict = {}

        orgs_to_update = [
            'Adventist-University-Of-Health-Sciences',
            'American-Public-University-System',
            'Brazosport-College',
            'Claflin-University',
            'Dyouville-College',
            'Excelsior-College',
            'Georgia-State-College-And-University',
            'Hagerstown-Community-College',
            'IUK',
            'University-of-Lynchburg',
            'McMurry-University',
            'MidAmerica-Nazarene-University',
            'Moreno-Valley-College',
            'Mount-Saint-Mary-College',
            'New-England-College',
            'NimblyWise',
            'North-Carolina-Central-University',
            'Rutgers-University',
            'San-Diego-Christian-College',
            'San-Joaquin-Valley-College',
            'Southern-New-Hampshire-University',
            'Southwest-Texas-Junior-College',
            'Spartanburg-Community-College',
            'Tarrant-County-College-District',
            'Thomas-Edison-State-University',
            'University-of-Lynchburg',
            'University-Of-Portsmouth',
            'Virginia-State-University',
            'William-Jewell-College',
            'Winston-Salem-State-University'
        ]

        connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                                 port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
        mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
        mongo_conn.authenticate(settings.CONTENTSTORE['DOC_STORE_CONFIG']['user'],
                                settings.CONTENTSTORE['DOC_STORE_CONFIG']['password'])

        source_course_data = get_course_structure(CourseKey.from_string(source_course_id))
        for block in source_course_data['blocks']:
            if block['block_type'] in ("problem", "openassessment") and block['asides']:
                block_id = self.get_block_id(block, mongo_conn)
                if block_id:
                    source_data_dict[block_id] = copy.deepcopy(block['asides'])

        for org_num, org in enumerate(orgs_to_update):
            print '-- Start process org: ', org_num, org
            courses = CourseOverview.objects.filter(org=org)
            for c in courses:
                if str(c.id) != source_course_id:
                    print '----- Start process course: ', str(c.id)
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
                if block_id and block_id in source_data_dict:
                    version_obj['blocks'][i]['asides'] = source_data_dict[block_id]
                    changed = True
            if changed:
                print 'Save!'
                structures.save(version_obj)
                cached_version = cache.get(str(version_obj['_id']))
                if cached_version:
                    print 'remove cache for: ', str(version_obj['_id'])
                    cache.delete(str(version_obj['_id']))
                update_course_structure.apply_async(
                    kwargs=dict(course_id=unicode(course_key), published_on=None),
                    countdown=10,
                )
