import hashlib
import json
from django.conf import settings
from django.contrib.auth.models import User
from pymongo import MongoClient
from pymongo.database import Database
from opaque_keys.edx.keys import UsageKey


def get_course_structure(course_key):
    connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                             port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
    mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
    mongo_conn.authenticate(settings.CONTENTSTORE['DOC_STORE_CONFIG']['user'],
                            settings.CONTENTSTORE['DOC_STORE_CONFIG']['password'])

    active_versions = mongo_conn.modulestore.active_versions
    course = active_versions.find_one({'org': course_key.org, 'course': course_key.course, 'run': course_key.run})
    if not course:
        return None

    structures = mongo_conn.modulestore.structures
    block_version = structures.find_one({'_id': course['versions']['published-branch']})
    return block_version


def _get_hash_from_set(data):
    data_lst = list(data)
    data_str = json.dumps(sorted(data_lst))
    return hashlib.md5(data_str.encode('utf-8')).hexdigest()


def get_unit_block_versions(block_id):
    usage_key = UsageKey.from_string(block_id)
    course_key = usage_key.course_key

    connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                             port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
    mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
    mongo_conn.authenticate(settings.CONTENTSTORE['DOC_STORE_CONFIG']['user'],
                            settings.CONTENTSTORE['DOC_STORE_CONFIG']['password'])

    active_versions = mongo_conn.modulestore.active_versions
    course = active_versions.find_one({'org': course_key.org, 'course': course_key.course, 'run': course_key.run})

    structures = mongo_conn.modulestore.structures
    block_version = structures.find_one({'_id': course['versions']['published-branch']})

    result = {}
    can_restore = False

    while block_version:
        block_found = False
        blocks_structure = {}
        for block in block_version['blocks']:
            blocks_structure[block['block_id']] = block

        for block in block_version['blocks']:
            if block['block_type'] == usage_key.block_type and block['block_id'] == usage_key.block_id:
                block_found = True
                edited_on_dt = block['edit_info']['edited_on']
                block_children = block['fields'].get('children', [])
                tmp_block_children_set = set()

                for child in block_children:
                    child_id = child[1]
                    if child_id in blocks_structure:
                        child_dict = blocks_structure[child_id]
                        tmp_block_children_set.add(child_id + '/' + str(child_dict['edit_info'].get('source_version', '-')))

                tmp_block_children_id = _get_hash_from_set(tmp_block_children_set)
                if tmp_block_children_id in result:
                    if edited_on_dt > result[tmp_block_children_id]['edited_on']:
                        break
                    can_restore = result[tmp_block_children_id]['can_restore']

                username = 'Unknown user'
                try:
                    user = User.objects.get(id=block['edit_info']['edited_by'])
                    username = user.username
                except User.DoesNotExist:
                    pass
                result[tmp_block_children_id] = {
                    'id': str(block_version['_id']),
                    'user': username,
                    'datetime': edited_on_dt.strftime("%B %d, %Y - %H:%M UTC"),
                    'can_restore': can_restore,
                    'edited_on': edited_on_dt
                }
                can_restore = True
                break
        if block_found:
            if block_version['previous_version']:
                block_version = structures.find_one({'_id': block_version['previous_version']})
            else:
                block_version = None
        else:
            block_version = None

    result = sorted(list(result.values()), key=lambda k: k['edited_on'])
    for d in result:
        del d['edited_on']
    return result[::-1]
