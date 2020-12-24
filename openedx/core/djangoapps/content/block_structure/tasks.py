"""
Asynchronous tasks related to the Course Blocks sub-application.
"""

import hashlib
import logging
import time
import json
from django.db import transaction
from django.utils.html import strip_tags

from celery.task import task
from django.conf import settings
from edxval.api import ValInternalError
from lxml.etree import XMLSyntaxError
from opaque_keys.edx.keys import CourseKey

from capa.responsetypes import LoncapaProblemError
from openedx.core.djangoapps.content.block_structure import api
from openedx.core.djangoapps.content.block_structure.config import STORAGE_BACKING_FOR_CACHE, waffle
from xmodule.modulestore.exceptions import ItemNotFoundError
from xmodule.modulestore.django import modulestore
from xmodule.modulestore import ModuleStoreEnum
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructure, ApiCourseStructureTags,\
    ApiCourseStructureLock, BlockToSequential, CourseAuthProfileFieldsCache, OraBlockStructure

log = logging.getLogger('edx.celery.task')

# TODO: TNL-5799 is ongoing; narrow these lists down until the general exception is no longer needed
RETRY_TASKS = (ItemNotFoundError, TypeError, ValInternalError)
NO_RETRY_TASKS = (XMLSyntaxError, LoncapaProblemError, UnicodeEncodeError)


def block_structure_task(**kwargs):
    """
    Decorator for block structure tasks.
    """
    return task(
        default_retry_delay=settings.BLOCK_STRUCTURES_SETTINGS['TASK_DEFAULT_RETRY_DELAY'],
        max_retries=settings.BLOCK_STRUCTURES_SETTINGS['TASK_MAX_RETRIES'],
        bind=True,
        **kwargs
    )


@block_structure_task()
def update_course_in_cache_v2(self, **kwargs):
    """
    Updates the course blocks (mongo -> BlockStructure) for the specified course.
    Keyword Arguments:
        course_id (string) - The string serialized value of the course key.
        with_storage (boolean) - Whether or not storage backing should be
            enabled for the generated block structure(s).
    """
    _update_course_in_cache(self, **kwargs)


@block_structure_task()
def update_course_in_cache(self, course_id):
    """
    Updates the course blocks (mongo -> BlockStructure) for the specified course.
    """
    _update_course_in_cache(self, course_id=course_id)


def _update_course_in_cache(self, **kwargs):
    """
    Updates the course blocks (mongo -> BlockStructure) for the specified course.
    """
    if kwargs.get('with_storage'):
        waffle().override_for_request(STORAGE_BACKING_FOR_CACHE)
    _call_and_retry_if_needed(self, api.update_course_in_cache, **kwargs)


@block_structure_task()
def get_course_in_cache_v2(self, **kwargs):
    """
    Gets the course blocks for the specified course, updating the cache if needed.
    Keyword Arguments:
        course_id (string) - The string serialized value of the course key.
        with_storage (boolean) - Whether or not storage backing should be
            enabled for any generated block structure(s).
    """
    _get_course_in_cache(self, **kwargs)


@block_structure_task()
def get_course_in_cache(self, course_id):
    """
    Gets the course blocks for the specified course, updating the cache if needed.
    """
    _get_course_in_cache(self, course_id=course_id)


@block_structure_task()
def update_course_structure(self, **kwargs):
    course_id = kwargs.get('course_id')
    published_on = kwargs.get('published_on')
    if course_id and course_id.startswith('course-v1'):
        lock = ApiCourseStructureLock.create(course_id)
        if not lock:
            raise self.retry(kwargs=kwargs, countdown=120)  # retry in 2 minutes

        try:
            _update_course_structure(course_id, published_on)
        except Exception as exc:
            log.exception('Error during update course %s structure: %s' % (str(course_id), str(exc)))
            raise self.retry(kwargs=kwargs, exc=exc)
        finally:
            ApiCourseStructureLock.remove(course_id)


def _get_course_in_cache(self, **kwargs):
    """
    Gets the course blocks for the specified course, updating the cache if needed.
    """
    if kwargs.get('with_storage'):
        waffle().override_for_request(STORAGE_BACKING_FOR_CACHE)
    _call_and_retry_if_needed(self, api.get_course_in_cache, **kwargs)


def _call_and_retry_if_needed(self, api_method, **kwargs):
    """
    Calls the given api_method with the given course_id, retrying task_method upon failure.
    """
    try:
        course_key = CourseKey.from_string(kwargs['course_id'])
        api_method(course_key)
    except NO_RETRY_TASKS:
        # Known unrecoverable errors
        log.exception(
            u"BlockStructure: %s encountered unrecoverable error in course %s, task_id %s",
            self.__name__,
            kwargs.get('course_id'),
            self.request.id,
        )
        raise
    except RETRY_TASKS as exc:
        log.exception(u"%s encountered expected error, retrying.", self.__name__)
        raise self.retry(kwargs=kwargs, exc=exc)
    except Exception as exc:
        log.exception(
            u"BlockStructure: %s encountered unknown error in course %s, task_id %s. Retry #%d",
            self.__name__,
            kwargs.get('course_id'),
            self.request.id,
            self.request.retries,
        )
        raise self.retry(kwargs=kwargs, exc=exc)


def _update_course_structure(course_id, published_on):
    allowed_categories = ['chapter', 'sequential', 'vertical', 'library_content', 'problem',
                          'openassessment', 'drag-and-drop-v2', 'image-explorer', 'html', 'video']
    course_key = CourseKey.from_string(course_id)
    t1 = time.time()

    with modulestore().branch_setting(ModuleStoreEnum.Branch.published_only):
        with modulestore().bulk_operations(course_key):
            try:
                course = modulestore().get_course(course_key, depth=0)
                if course:
                    if course.credo_additional_profile_fields:
                        mongo_profile_fields = course.credo_additional_profile_fields
                        try:
                            profile_fields_cache = CourseAuthProfileFieldsCache.objects.get(course_id=course_id)
                            profile_fields_cache_fields = profile_fields_cache.get_fields()
                            if not profile_fields_cache_fields or set(profile_fields_cache_fields.keys()) != set(mongo_profile_fields.keys()):
                                profile_fields_cache.data = json.dumps(mongo_profile_fields)
                                profile_fields_cache.save()
                        except CourseAuthProfileFieldsCache.DoesNotExist:
                            profile_fields_cache = CourseAuthProfileFieldsCache(
                                course_id=course_id,
                                data=json.dumps(mongo_profile_fields)
                            )
                            profile_fields_cache.save()
                    else:
                        try:
                            profile_fields_cache = CourseAuthProfileFieldsCache.objects.get(course_id=course_id)
                            profile_fields_cache.delete()
                        except CourseAuthProfileFieldsCache.DoesNotExist:
                            pass
                else:
                    return

                if published_on:
                    published_on = published_on.split('.')[0]
                current_published_on = str(course.published_on).split('.')[0]
                if published_on is not None and current_published_on != published_on:
                    log.info("Skip outdated task for course %s. Course.published_on %s != passed published_on %s"
                             % (str(course_id), current_published_on, published_on))
                    return
                data = modulestore().get_items(course_key)
            except ItemNotFoundError:
                log.exception("Course isn't exist or not published: %s" % str(course_id))
                return

    t2 = time.time()

    existing_structure_items = ApiCourseStructure.objects.filter(course_id=str(course_id))
    existing_structure_items_dict = {s.block_id: s for s in existing_structure_items}

    existing_structure_tags_dict = {}
    existing_structure_tags = ApiCourseStructureTags.objects.filter(course_id=str(course_id))
    for tag in existing_structure_tags:
        if tag.rubric:
            k = tag.block_id + '|' + tag.rubric + '|' + tag.tag_name + '|' + tag.tag_value
        else:
            k = tag.block_id + '|__|' + tag.tag_name + '|' + tag.tag_value
        existing_structure_tags_dict[k] = tag

    block_to_sequential_items = BlockToSequential.objects.filter(course_id=str(course_id))
    block_to_sequential_items_dict = {b2s.block_id: b2s for b2s in block_to_sequential_items}

    ora_blocks = OraBlockStructure.objects.filter(course_id=str(course_id))
    ora_blocks_dict = {o.block_id: o for o in ora_blocks}

    t3 = time.time()

    structure_dict = {}
    structure_tags = []
    for item in data:
        if item.category in allowed_categories:
            structure_dict[str(item.location)] = item

    items_to_insert = []
    ora_to_insert = []
    tags_to_insert = []
    b2s_to_insert = []
    items_updated = 0
    b2s_updated = 0
    ora_items_updated = 0
    course_location = str(course.location)

    if course_location not in existing_structure_items_dict:
        items_to_insert.append(
            ApiCourseStructure(
                block_id=course_location,
                block_type='course',
                course_id=course_id,
                display_name=course.display_name.strip().replace('|', ' ').replace('$', ' '),
                graded=0,
                parent_id=None,
                section_path=None
            )
        )

    with transaction.atomic():
        for item in data:
            if item.category in allowed_categories and item.parent and item.display_name:
                block_id = str(item.location)
                if block_id not in existing_structure_items_dict:
                    graded = 1 if item.graded else 0
                    block_item = ApiCourseStructure(
                        block_id=block_id,
                        block_type=item.category,
                        course_id=course_id,
                        display_name=item.display_name.strip().replace('|', ' ').replace('$', ' '),
                        graded=graded,
                        parent_id=str(item.parent),
                        section_path=_get_section_path(item, structure_dict)
                    )
                    items_to_insert.append(block_item)
                else:
                    block_item = existing_structure_items_dict[block_id]
                    section_path = _get_section_path(item, structure_dict)
                    item_display_name = item.display_name.strip().replace('|', ' ').replace('$', ' ')
                    if block_item.display_name != item_display_name\
                      or block_item.graded != item.graded\
                      or block_item.section_path != section_path:
                        block_item.display_name = item_display_name
                        block_item.graded = item.graded
                        block_item.section_path = section_path
                        block_item.save()
                        items_updated += 1

                if item.category == 'openassessment':
                    is_ora_empty_rubrics = len(item.rubric_criteria) == 0
                    ora_rubric_criteria = json.dumps(item.rubric_criteria)
                    ora_steps_lst = []

                    if not is_ora_empty_rubrics:
                        for step in item.rubric_assessments:
                            if step['name'] == 'peer-assessment':
                                ora_steps_lst.append('peer')
                            elif step['name'] == 'self-assessment':
                                ora_steps_lst.append('self')
                            elif step['name'] == 'staff-assessment':
                                ora_steps_lst.append('staff')
                    ora_steps = json.dumps(sorted(ora_steps_lst))

                    ora_prompt = _get_ora_question_text(item)
                    ora_item = ora_blocks_dict.get(block_id)

                    if not ora_item:
                        ora_item = OraBlockStructure(
                            course_id=course_id,
                            org_id=course_key.org,
                            block_id=block_id,
                            is_ora_empty_rubrics=is_ora_empty_rubrics,
                            support_multiple_rubrics=item.support_multiple_rubrics,
                            is_additional_rubric=item.is_additional_rubric,
                            prompt=ora_prompt,
                            rubric_criteria=ora_rubric_criteria,
                            display_rubric_step_to_students=item.display_rubric_step_to_students,
                            steps=ora_steps
                        )
                        ora_to_insert.append(ora_item)
                    elif is_ora_empty_rubrics != ora_item.is_ora_empty_rubrics\
                      or item.support_multiple_rubrics != ora_item.support_multiple_rubrics\
                      or item.is_additional_rubric != ora_item.is_additional_rubric\
                      or item.prompt != ora_prompt\
                      or item.display_rubric_step_to_students != ora_item.display_rubric_step_to_students \
                      or ora_rubric_criteria != ora_item.rubric_criteria \
                      or ora_steps != ora_item.steps:
                        ora_item.is_ora_empty_rubrics = is_ora_empty_rubrics
                        ora_item.support_multiple_rubrics = item.support_multiple_rubrics
                        ora_item.is_additional_rubric = item.is_additional_rubric
                        ora_item.prompt = ora_prompt
                        ora_item.rubric_criteria = ora_rubric_criteria
                        ora_item.display_rubric_step_to_students = item.display_rubric_step_to_students
                        ora_item.steps = ora_steps
                        ora_item.save()
                        ora_items_updated += 1

                if item.category in ('problem', 'drag-and-drop-v2', 'image-explorer', 'openassessment'):
                    parent = _get_parent_sequential(item, structure_dict)
                    if parent:
                        parent_id = str(parent.location)
                        parent_graded = 1 if parent.graded else 0
                        if block_id not in block_to_sequential_items_dict:
                            b2s_to_insert.append(BlockToSequential(
                                block_id=block_id,
                                sequential_id=parent_id,
                                sequential_name=parent.display_name.strip(),
                                course_id=course_id,
                                graded=parent_graded,
                                visible_to_staff_only=item.visible_to_staff_only
                            ))
                        else:
                            b2s_item = block_to_sequential_items_dict[block_id]
                            if b2s_item.sequential_name != parent.display_name.strip() \
                              or b2s_item.graded != parent_graded\
                              or b2s_item.visible_to_staff_only != item.visible_to_staff_only:
                                b2s_item.sequential_name = parent.display_name.strip()
                                b2s_item.graded = parent_graded
                                b2s_item.visible_to_staff_only = item.visible_to_staff_only
                                b2s_item.save()
                                b2s_updated += 1

                if item.category in ('problem', 'drag-and-drop-v2', 'image-explorer', 'html', 'video')\
                    or (item.category == 'openassessment' and len(item.rubric_criteria) == 0):
                    aside = item.runtime.get_aside_of_type(item, 'tagging_aside')
                    if isinstance(aside.saved_tags, dict):
                        for tag_name, tag_values in aside.saved_tags.items():
                            if isinstance(tag_values, list):
                                for tag_value in tag_values:
                                    t_name = tag_name.strip()
                                    t_value = tag_value.strip()
                                    if not t_value:
                                        continue

                                    t_value_lst = t_value.split(' - ')

                                    root_tag_value_hash = hashlib.md5(
                                        t_value_lst[0].strip().encode('utf-8')).hexdigest()

                                    for idx, _ in enumerate(t_value_lst):
                                        t_value_upd = ' - '.join(t_value_lst[0:idx + 1])
                                        tag_id = block_id + '|__|' + t_name + '|' + t_value_upd
                                        structure_tags.append(tag_id)
                                        if tag_id not in existing_structure_tags_dict:
                                            is_parent = 1 if len(t_value_lst) > idx + 1 else 0
                                            block_tag_id = hashlib.md5(block_id.encode('utf-8')).hexdigest()

                                            tags_to_insert.append(ApiCourseStructureTags(
                                                org_id=course_key.org,
                                                course_id=course_id,
                                                block=block_item,
                                                block_tag_id=block_tag_id,
                                                root_tag_value_hash=root_tag_value_hash,
                                                rubric=None,
                                                tag_name=t_name,
                                                tag_value=t_value_upd,
                                                is_parent=is_parent,
                                                ts=int(time.time())
                                            ))
                elif item.category == 'openassessment' and len(item.rubric_criteria) > 0:
                    aside = item.runtime.get_aside_of_type(item, 'tagging_ora_aside')
                    for rubric, saved_tags in aside.saved_tags.items():
                        if isinstance(saved_tags, dict):
                            for tag_name, tag_values in saved_tags.items():
                                if isinstance(tag_values, list):
                                    for tag_value in tag_values:
                                        r_name = rubric.strip()
                                        t_name = tag_name.strip()
                                        t_value = tag_value.strip()
                                        if not t_value:
                                            continue

                                        t_value_lst = t_value.split(' - ')
                                        root_tag_value_hash = hashlib.md5(
                                            t_value_lst[0].strip().encode('utf-8')).hexdigest()

                                        for idx, _ in enumerate(t_value_lst):
                                            t_value_upd = ' - '.join(t_value_lst[0:idx + 1])
                                            tag_id = block_id + '|' + r_name + '|' + t_name + '|' + t_value_upd
                                            structure_tags.append(tag_id)
                                            if tag_id not in existing_structure_tags_dict:
                                                is_parent = 1 if len(t_value_lst) > idx + 1 else 0
                                                block_token = block_id + '|' + r_name
                                                block_tag_id = hashlib.md5(block_token.encode('utf-8')).hexdigest()

                                                tags_to_insert.append(ApiCourseStructureTags(
                                                    org_id=course_key.org,
                                                    course_id=course_id,
                                                    block=block_item,
                                                    block_tag_id=block_tag_id,
                                                    root_tag_value_hash=root_tag_value_hash,
                                                    rubric=r_name,
                                                    tag_name=t_name,
                                                    tag_value=t_value_upd,
                                                    is_parent=is_parent,
                                                    ts=int(time.time())
                                                ))

        items_to_remove = []
        for block_id, block_item in existing_structure_items_dict.items():
            if block_id not in structure_dict and block_item.block_type != 'course' and not block_item.deleted:
                items_to_remove.append(block_item.id)
        if items_to_remove:
            ApiCourseStructure.objects.filter(id__in=items_to_remove).update(deleted=True)

        if items_to_insert:
            ApiCourseStructure.objects.bulk_create(items_to_insert)

        b2s_to_remove = []
        for b2s_id, b2s_item in block_to_sequential_items_dict.items():
            if b2s_id not in structure_dict and not b2s_item.deleted:
                b2s_to_remove.append(b2s_item.id)
        if b2s_to_remove:
            BlockToSequential.objects.filter(id__in=b2s_to_remove).update(deleted=True)

        if b2s_to_insert:
            BlockToSequential.objects.bulk_create(b2s_to_insert)

        tags_to_remove = []
        for tag_id, tag in existing_structure_tags_dict.items():
            if tag_id not in structure_tags:
                tags_to_remove.append(tag.id)
        if tags_to_remove:
            ApiCourseStructureTags.objects.filter(id__in=tags_to_remove).delete()

        if tags_to_insert:
            ApiCourseStructureTags.objects.bulk_create(tags_to_insert)

        ora_to_remove = []
        for ora_id, ora_item in ora_blocks_dict.items():
            if ora_id not in structure_dict:
                ora_to_remove.append(ora_item.id)
        if ora_to_remove:
            OraBlockStructure.objects.filter(id__in=ora_to_remove).delete()

        if ora_to_insert:
            OraBlockStructure.objects.bulk_create(ora_to_insert)

        t4 = time.time()
        time_total = t4 - t1
        time_to_get_structure_from_mongo = t2 - t1
        time_to_get_mysql_structure = t3 - t2
        time_to_update_data_in_mysql = t4 - t3

        log.info("Update %s structure results: added %s items, updated %s items, removed %s items, "
                 "added %s tags, removed %s tags, added %s b2s, updated %s b2s, removed %s b2s. "
                 "Time to get data from mongo: %s. Time to get data from Mysql: %s. Time to update data in Mysql: %s. "
                 "Total time: %s"
                 % (str(course_id), str(len(items_to_insert)), str(items_updated), str(len(items_to_remove)),
                    str(len(tags_to_insert)), str(len(tags_to_remove)), str(len(b2s_to_insert)),
                    str(b2s_updated), str(len(b2s_to_remove)), str(time_to_get_structure_from_mongo),
                    str(time_to_get_mysql_structure), str(time_to_update_data_in_mysql), str(time_total)))


def _get_section_path(block, structure_dict):
    if block.category not in ('sequential', 'vertical', 'chapter'):
        return None

    parent_id = str(block.parent)
    parent = structure_dict.get(parent_id)
    block_path = [_process_display_name(block)]

    while parent and parent.category != 'course':
        block_path.append(_process_display_name(parent))
        parent_id = str(parent.parent) if parent.category != 'chapter' else None
        parent = structure_dict.get(parent_id) if parent_id else None

    return '|'.join(reversed(block_path))


def _process_display_name(block):
    display_name = ''
    if block.display_name:
        display_name = block.display_name.strip() or ''
    return display_name.replace('|', ' ').replace('$', ' ')


def _get_parent_sequential(block, structure_dict):
    if block.category == 'sequential':
        return block
    parent_id = str(block.parent)
    parent = structure_dict.get(parent_id)
    return _get_parent_sequential(parent, structure_dict) if parent else None


def _get_ora_question_text(ora_block):
    prompts = []
    brs_tags = ['<br>', '<br/>', '<br />']
    for pr in ora_block.prompts:
        pr_descr = pr['description']
        for br_val in brs_tags:
            pr_descr = pr_descr.replace(br_val, "\n")
        prompts.append(strip_tags(pr_descr).strip())

    if len(prompts) > 1:
        return "\n".join(prompts)
    elif len(prompts) == 1:
        return prompts[0]
