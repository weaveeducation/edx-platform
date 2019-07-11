from collections import OrderedDict
from django.conf import settings
from django.contrib.auth.models import User
from pymongo import MongoClient
from pymongo.database import Database
from opaque_keys.edx.keys import UsageKey


def get_block_versions(block_id):
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

    result = OrderedDict()
    last_published = True

    while block_version:
        block_found = False
        for block in block_version['blocks']:
            if block['block_type'] == usage_key.block_type and block['block_id'] == usage_key.block_id:
                block_found = True
                edited_on = str(block['edit_info']['edited_on'])

                if edited_on not in result:
                    username = 'Unknown user'
                    try:
                        user = User.objects.get(id=block['edit_info']['edited_by'])
                        username = user.username
                    except User.DoesNotExist:
                        pass
                    result[edited_on] = {
                        'id': str(block_version['_id']),
                        'user': username,
                        'datetime': block['edit_info']['edited_on'].strftime("%B %d, %Y - %H:%M UTC"),
                        'can_restore': not last_published
                    }
                    last_published = False
        if block_found:
            if block_version['previous_version']:
                block_version = structures.find_one({'_id': block_version['previous_version']})
            else:
                block_version = None
        else:
            block_version = None
    return result.values()
