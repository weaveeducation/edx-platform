"""
Asynchronous tasks related to the Course Blocks sub-application.
"""
import logging
import time
from django.db import transaction

from capa.responsetypes import LoncapaProblemError
from celery.task import task
from django.conf import settings
from lxml.etree import XMLSyntaxError

from edxval.api import ValInternalError
from opaque_keys.edx.keys import CourseKey

from xmodule.modulestore.django import modulestore
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.exceptions import ItemNotFoundError
from openedx.core.djangoapps.content.block_structure import api
from openedx.core.djangoapps.content.block_structure.config import STORAGE_BACKING_FOR_CACHE, waffle
from openedx.core.djangoapps.content.block_structure.models import ApiCourseStructure, ApiCourseStructureTags,\
    ApiCourseStructureLock, BlockToSequential

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
def update_course_structure(self, **kwargs):
    course_id = kwargs.get('course_id')
    published_on = kwargs.get('published_on')
    if course_id:
        lock = ApiCourseStructureLock.create(course_id)
        if not lock:
            raise self.retry(kwargs=kwargs, countdown=120)  # retry in 2 minutes

        try:
            _update_course_structure(course_id, published_on)
        except Exception, exc:
            log.exception('Error during update course %s structure: %s' % (str(course_id), str(exc)))
            raise self.retry(kwargs=kwargs, exc=exc)
        finally:
            ApiCourseStructureLock.remove(course_id)


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
            "BlockStructure: %s encountered unrecoverable error in course %s, task_id %s",
            self.__name__,
            kwargs.get('course_id'),
            self.request.id,
        )
        raise
    except RETRY_TASKS as exc:
        log.exception("%s encountered expected error, retrying.", self.__name__)
        raise self.retry(kwargs=kwargs, exc=exc)
    except Exception as exc:
        log.exception(
            "BlockStructure: %s encountered unknown error in course %s, task_id %s. Retry #%d",
            self.__name__,
            kwargs.get('course_id'),
            self.request.id,
            self.request.retries,
        )
        raise self.retry(kwargs=kwargs, exc=exc)


def _update_course_structure(course_id, published_on):
    allowed_categories = ['chapter', 'sequential', 'vertical', 'library_content', 'problem',
                          'openassessment', 'drag-and-drop-v2', 'html', 'video']
    course_key = CourseKey.from_string(course_id)
    t1 = time.time()

    with modulestore().branch_setting(ModuleStoreEnum.Branch.published_only):
        with modulestore().bulk_operations(course_key):
            try:
                course = modulestore().get_course(course_key, depth=0)
                if published_on is not None and unicode(course.published_on) != published_on:
                    log.info("Skip outdated task for course %s. Course.published_on %s != passed published_on %s"
                             % (str(course_id), unicode(course.published_on), published_on))
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

    t3 = time.time()

    structure_dict = {}
    structure_tags = []
    for item in data:
        if item.category in allowed_categories:
            structure_dict[str(item.location)] = item

    items_to_insert = []
    tags_to_insert = []
    b2s_to_insert = []
    items_updated = 0
    b2s_updated = 0
    course_location = str(course.location)

    if course_location not in existing_structure_items_dict:
        items_to_insert.append(
            ApiCourseStructure(
                block_id=course_location,
                block_type='course',
                course_id=course_id,
                display_name=course.display_name.strip(),
                graded=0,
                parent_id=None,
                section_path=None
            )
        )

    with transaction.atomic():
        for item in data:
            if item.category in allowed_categories:
                block_id = str(item.location)
                if block_id not in existing_structure_items_dict:
                    graded = 1 if item.graded else 0
                    block_item = ApiCourseStructure(
                        block_id=block_id,
                        block_type=item.category,
                        course_id=course_id,
                        display_name=item.display_name.strip(),
                        graded=graded,
                        parent_id=str(item.parent),
                        section_path=_get_section_path(item, structure_dict)
                    )
                    items_to_insert.append(block_item)
                else:
                    block_item = existing_structure_items_dict[block_id]
                    section_path = _get_section_path(item, structure_dict)
                    if block_item.display_name != item.display_name.strip()\
                      or block_item.graded != item.graded\
                      or block_item.section_path != section_path:
                        block_item.display_name = item.display_name.strip()
                        block_item.graded = item.graded
                        block_item.section_path = section_path
                        block_item.save()
                        items_updated += 1

                if item.category in ('problem', 'drag-and-drop-v2', 'openassessment'):
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
                            ))
                        else:
                            b2s_item = block_to_sequential_items_dict[block_id]
                            if b2s_item.sequential_name != parent.display_name.strip() or b2s_item.graded != parent_graded:
                                b2s_item.sequential_name = parent.display_name.strip()
                                b2s_item.graded = parent_graded
                                b2s_item.save()
                                b2s_updated += 1

                if item.category in ('problem', 'drag-and-drop-v2', 'html', 'video')\
                    or (item.category == 'openassessment' and len(item.rubric_criteria) == 0):
                    aside = item.runtime.get_aside_of_type(item, 'tagging_aside')
                    if isinstance(aside.saved_tags, dict):
                        for tag_name, tag_values in aside.saved_tags.items():
                            if isinstance(tag_values, list):
                                for tag_value in tag_values:
                                    t_name = tag_name.strip()
                                    t_value = tag_value.strip()
                                    tag_id = block_id + '|__|' + t_name + '|' + t_value
                                    structure_tags.append(tag_id)
                                    if tag_id not in existing_structure_tags_dict:
                                        tags_to_insert.append(ApiCourseStructureTags(
                                            course_id=course_id,
                                            block=block_item,
                                            rubric=None,
                                            tag_name=t_name,
                                            tag_value=t_value
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
                                        tag_id = block_id + '|' + r_name + '|' + t_name + '|' + t_value
                                        structure_tags.append(tag_id)
                                        if tag_id not in existing_structure_tags_dict:
                                            tags_to_insert.append(ApiCourseStructureTags(
                                                course_id=course_id,
                                                block=block_item,
                                                rubric=r_name,
                                                tag_name=t_name,
                                                tag_value=t_value
                                            ))

        items_to_remove = []
        for block_id, block_item in existing_structure_items_dict.items():
            if block_id not in structure_dict and block_item.block_type != 'course':
                items_to_remove.append(block_item.id)
        if items_to_remove:
            ApiCourseStructure.objects.filter(id__in=items_to_remove).delete()

        if items_to_insert:
            ApiCourseStructure.objects.bulk_create(items_to_insert)

        b2s_to_remove = []
        for b2s_id, b2s_item in block_to_sequential_items_dict.items():
            if b2s_id not in structure_dict:
                b2s_to_remove.append(b2s_item.id)
        if b2s_to_remove:
            BlockToSequential.objects.filter(id__in=b2s_to_remove).delete()

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
    display_name = block.display_name.strip() or ''
    return display_name.replace('|', ' ')


def _get_parent_sequential(block, structure_dict):
    if block.category == 'sequential':
        return block
    parent_id = str(block.parent)
    parent = structure_dict.get(parent_id)
    return _get_parent_sequential(parent, structure_dict) if parent else None
