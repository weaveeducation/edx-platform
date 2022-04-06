import hashlib
import json
from bson.objectid import ObjectId
from django.conf import settings
from django.contrib.auth import get_user_model
from pymongo import MongoClient
from pymongo.database import Database
from opaque_keys.edx.keys import UsageKey, CourseKey


User = get_user_model()


def _get_mongo_connection():
    connection = MongoClient(host=settings.CONTENTSTORE['DOC_STORE_CONFIG']['host'],
                             port=settings.CONTENTSTORE['DOC_STORE_CONFIG']['port'])
    mongo_conn = Database(connection, settings.CONTENTSTORE['DOC_STORE_CONFIG']['db'])
    mongo_conn.authenticate(settings.CONTENTSTORE['DOC_STORE_CONFIG']['user'],
                            settings.CONTENTSTORE['DOC_STORE_CONFIG']['password'])
    return mongo_conn


def _get_hash_from_set(data):
    data_lst = list(data)
    data_str = json.dumps(sorted(data_lst))
    return hashlib.md5(data_str.encode('utf-8')).hexdigest()


def get_last_published_course_version(course_key):
    mongo_conn = _get_mongo_connection()

    active_versions = mongo_conn.modulestore.active_versions
    course = active_versions.find_one({'org': course_key.org, 'course': course_key.course, 'run': course_key.run})
    if not course:
        return None
    return str(course['versions']['published-branch'])


def get_course_structure(course_key):
    mongo_conn = _get_mongo_connection()

    active_versions = mongo_conn.modulestore.active_versions
    course = active_versions.find_one({'org': course_key.org, 'course': course_key.course, 'run': course_key.run})
    if not course:
        return None

    structures = mongo_conn.modulestore.structures
    block_version = structures.find_one({'_id': course['versions']['published-branch']})
    return block_version


def get_unit_block_versions(block_id, course_version_id=None):
    usage_key = UsageKey.from_string(block_id)
    course_key = usage_key.course_key

    mongo_conn = _get_mongo_connection()

    active_versions = mongo_conn.modulestore.active_versions
    course = active_versions.find_one({'org': course_key.org, 'course': course_key.course, 'run': course_key.run})

    structures = mongo_conn.modulestore.structures
    initial_block_id = ObjectId(course_version_id) if course_version_id else course['versions']['published-branch']
    block_version = structures.find_one({'_id': initial_block_id})

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


def get_versions_for_blocks(course_id, blocks_id, course_version_id=None):
    course_key = CourseKey.from_string(course_id)

    mongo_conn = _get_mongo_connection()

    active_versions = mongo_conn.modulestore.active_versions
    course = active_versions.find_one({'org': course_key.org, 'course': course_key.course, 'run': course_key.run})

    structures = mongo_conn.modulestore.structures
    initial_block_id = ObjectId(course_version_id) if course_version_id else course['versions']['published-branch']
    block_version = structures.find_one({'_id': initial_block_id})

    result = {}
    can_restore = {usage_id: False for usage_id in blocks_id}
    block_id_dict = {}
    for usage_id in blocks_id:
        usage_key = UsageKey.from_string(usage_id)
        block_id = usage_key.block_id
        block_id_dict[block_id] = usage_id

    while block_version:
        found_num = 0
        blocks_structure = {}
        for block in block_version['blocks']:
            blocks_structure[block['block_id']] = block

        for block in block_version['blocks']:
            if block['block_id'] in block_id_dict:
                found_num += 1
                usage_id = block_id_dict[block['block_id']]
                if usage_id not in result:
                    result[usage_id] = {}
                edited_on_dt = block['edit_info']['edited_on']
                block_children = block['fields'].get('children', [])
                tmp_block_children_set = set()

                for child in block_children:
                    child_id = child[1]
                    if child_id in blocks_structure:
                        child_dict = blocks_structure[child_id]
                        tmp_block_children_set.add(child_id + '/' + str(child_dict['edit_info'].get('source_version', '-')))

                tmp_block_children_id = _get_hash_from_set(tmp_block_children_set)
                if tmp_block_children_id in result[usage_id]:
                    if edited_on_dt > result[usage_id][tmp_block_children_id]['edited_on']:
                        break
                    can_restore[usage_id] = result[usage_id][tmp_block_children_id]['can_restore']

                username = 'Unknown user'
                try:
                    user = User.objects.get(id=block['edit_info']['edited_by'])
                    username = user.username
                except User.DoesNotExist:
                    pass
                result[usage_id][tmp_block_children_id] = {
                    'id': str(block_version['_id']),
                    'user': username,
                    'datetime': edited_on_dt.strftime("%B %d, %Y - %H:%M UTC"),
                    'can_restore': can_restore[usage_id],
                    'edited_on': edited_on_dt
                }
                can_restore[usage_id] = True

        if found_num != 0:
            if block_version['previous_version']:
                block_version = structures.find_one({'_id': block_version['previous_version']})
            else:
                block_version = None
        else:
            block_version = None

    res = {}
    for usage_id, items_dict in result.items():
        tmp_res = sorted(list(items_dict.values()), key=lambda k: k['edited_on'])
        for d in tmp_res:
            del d['edited_on']
        res[usage_id] = tmp_res[::-1]
    return res
