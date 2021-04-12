import logging
from uuid import uuid4
from collections import OrderedDict

from django.db import transaction, IntegrityError
from django.contrib.auth.models import User
from django.utils import timezone
from util.module_utils import yield_dynamic_descriptor_descendants
from openedx.core.djangoapps.content.block_structure.models import ApiBlockInfo
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from opaque_keys.edx.keys import CourseKey, UsageKey
from credo_modules.mongo import get_last_published_block_version, get_last_published_course_version
from credo_modules.models import SiblingBlockUpdateTask, SiblingBlockNotUpdated
from celery.task import task
from student.auth import has_studio_write_access
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from xblock.fields import Scope


log = logging.getLogger(__name__)


def create_api_block_info(usage_key, user, block_hash_id=None, created_as_copy=False,
                          published_after_copy=False, auto_save=True):
    if not block_hash_id:
        block_hash_id = str(uuid4())

    api_block_info = ApiBlockInfo(
        course_id=str(usage_key.course_key),
        block_id=str(usage_key),
        hash_id=block_hash_id,
        created_by=user.id,
        created_time=timezone.now(),
        updated_by=user.id,
        updated_time=timezone.now(),
        created_as_copy=created_as_copy,
        published_after_copy=published_after_copy
    )
    api_block_info.set_has_children()
    if auto_save:
        api_block_info.save()
    return api_block_info


def copy_api_block_info(source_item, dest_module, user, level=0, auto_save=True, force=False):
    src_course_id = str(source_item.location.course_key)
    dst_course_id = str(dest_module.location.course_key)

    if ((level == 0 and source_item.category not in ApiBlockInfo.CATEGORY_HAS_CHILDREN)
      or src_course_id == dst_course_id) and not force:
        source_block_hash = str(uuid4())
    else:
        source_block_hash = None
        try:
            with transaction.atomic():
                source_block_info = ApiBlockInfo.objects.filter(block_id=str(source_item.location)).first()
                if source_block_info:
                    source_block_hash = source_block_info.hash_id
                else:
                    source_block_info = create_api_block_info(source_item.location, user)
                    source_block_hash = source_block_info.hash_id
        except IntegrityError:
            source_block_info = ApiBlockInfo.objects.filter(block_id=str(source_item.location)).first()
            if source_block_info:
                source_block_hash = source_block_info.hash_id

    return create_api_block_info(dest_module.location, user, block_hash_id=source_block_hash,
                                 created_as_copy=True, auto_save=auto_save)


def update_api_blocks_before_publish(xblock, user):
    block_id = str(xblock.location)
    course_id = str(xblock.location.course_key)
    api_block_info = ApiBlockInfo.objects.filter(
        course_id=course_id, block_id=block_id,
        created_as_copy=True, published_after_copy=False, deleted=False).first()

    if api_block_info:
        if api_block_info.has_children:
            block_ids = [str(module.location) for module in yield_dynamic_descriptor_descendants(xblock, user.id)]
            ApiBlockInfo.objects.filter(course_id=course_id, block_id__in=block_ids, deleted=False)\
                .update(published_after_copy=True)
        else:
            api_block_info.published_after_copy = True
            api_block_info.save()

        if xblock.category != 'chapter':
            xblock_parent = xblock.get_parent()
            children_block_ids = [str(child) for child in xblock_parent.children]
            api_block_info_same_level_cnt = ApiBlockInfo.objects.filter(
                course_id=course_id, block_id__in=children_block_ids,
                created_as_copy=True, published_after_copy=False, deleted=False).count()
            if api_block_info_same_level_cnt == 0:
                update_api_blocks_before_publish(xblock_parent, user)

        return False
    return True


def update_sibling_block_after_publish(related_courses, xblock, xblock_is_published, user):
    task_uuid = str(uuid4())
    if related_courses and xblock.category in ApiBlockInfo.CATEGORY_HAS_CHILDREN:
        update_res = []
        for related_course_id, course_action in related_courses.items():
            if course_action in ('publish', 'draft'):
                if has_studio_write_access(user, CourseKey.from_string(related_course_id)):
                    with transaction.atomic():
                        sibling_block_update_task = SiblingBlockUpdateTask(
                            task_id=task_uuid,
                            initiator=user,
                            source_course_id=str(xblock.location.course_key),
                            source_block_id=str(xblock.location),
                            sibling_course_id=str(related_course_id),
                            published=bool(course_action == 'publish')
                        )
                        sibling_block_update_task.save()
                        update_res.append((sibling_block_update_task.id, related_course_id, course_action))
            elif xblock_is_published:
                set_sibling_block_not_updated.delay(str(xblock.location), related_course_id, user.id)

        if update_res:
            transaction.on_commit(lambda: [update_sibling_block_in_related_course.delay(
                task_id, str(xblock.location), rel_course_id, rel_course_action == 'publish', user.id)
                for task_id, rel_course_id, rel_course_action in update_res])
            return task_uuid
    return None


def _copy_fields_from_one_xblock_to_other(store, source_block, dst_block_id, user, save_xblock_fn):
    dst_item = store.get_item(UsageKey.from_string(dst_block_id))

    metadata = {}
    for field in source_block.fields.values():
        if field.scope == Scope.settings and field.is_set_on(source_block):
            metadata[field.name] = field.read_from(source_block)
    data = getattr(source_block, 'data', None)
    if data and not isinstance(data, str):
        data = None

    asides_to_update = None
    for aside in source_block.runtime.get_asides(source_block):
        for field in aside.fields.values():
            if field.scope in (Scope.settings, Scope.content,) and field.is_set_on(aside):
                asides_to_update = [aside]
                break

    save_xblock_fn(user, dst_item, data=data, metadata=metadata, asides=asides_to_update)
    return dst_item


@task()
def set_sibling_block_not_updated(source_usage_id, dst_course_id, user_id):
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        return

    source_usage_key = UsageKey.from_string(source_usage_id)
    source_course_key = source_usage_key.course_key
    course_id = str(source_course_key)

    store = modulestore()
    source_block_parents_path_lst = []
    source_block_parents_path = None

    with store.bulk_operations(source_course_key):
        item = store.get_item(source_usage_key)
        source_block_name = item.display_name
        parent_block = item.get_parent()
        while parent_block and parent_block.category != 'course':
            source_block_parents_path_lst.append(parent_block.display_name)
            parent_block = parent_block.get_parent()
    if source_block_parents_path_lst:
        source_block_parents_path_lst.reverse()
        source_block_parents_path = ' > '.join(source_block_parents_path_lst)

    source_main_block_info = ApiBlockInfo.objects.filter(
        block_id=str(source_usage_id), course_id=course_id, has_children=True, deleted=False).first()
    if not source_main_block_info:
        return

    dst_main_block_info = ApiBlockInfo.objects.filter(
        hash_id=source_main_block_info.hash_id, course_id=dst_course_id, deleted=False).first()
    if not dst_main_block_info:
        return

    sibling_version_published = None
    sibling_version_publisher_user_id = None
    published_block_info = get_last_published_block_version(dst_main_block_info.block_id)
    if published_block_info:
        sibling_version_published = timezone.make_aware(published_block_info['datetime'])
        sibling_version_publisher_user_id = published_block_info['user_id']

    try:
        sibling_block_not_updated = SiblingBlockNotUpdated.objects.get(
            source_course_id=course_id,
            source_block_id=source_usage_id,
            sibling_course_id=dst_course_id,
            sibling_block_id=dst_main_block_info.block_id
        )
    except SiblingBlockNotUpdated.DoesNotExist:
        sibling_block_not_updated = SiblingBlockNotUpdated(
            source_course_id=course_id,
            source_block_id=source_usage_id,
            sibling_course_id=dst_course_id,
            sibling_block_id=dst_main_block_info.block_id,
        )
    sibling_block_not_updated.source_block_name = source_block_name
    sibling_block_not_updated.source_block_parents_path = source_block_parents_path
    sibling_block_not_updated.source_version_published_date = timezone.now()
    sibling_block_not_updated.source_version_publisher_user_id = user.id
    sibling_block_not_updated.sibling_version_published_date = sibling_version_published
    sibling_block_not_updated.sibling_version_publisher_user_id = sibling_version_publisher_user_id
    sibling_block_not_updated.save()


@task()
def update_sibling_block_in_related_course(task_id, source_usage_id, dst_course_id, need_publish, user_id):
    from .item import _save_xblock as save_xblock_fn, _delete_item as delete_xblock_fn,\
        _duplicate_item as duplicate_xblock_fn

    try:
        sibling_update_task = SiblingBlockUpdateTask.objects.get(id=task_id)
    except SiblingBlockUpdateTask.DoesNotExist:
        return

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        sibling_update_task.set_error()
        sibling_update_task.save()
        return

    try:
        sibling_update_task.set_started()
        sibling_update_task.save()

        source_usage_key = UsageKey.from_string(source_usage_id)
        source_course_key = source_usage_key.course_key
        dst_course_key = CourseKey.from_string(dst_course_id)

        course_id = str(source_course_key)
        items_to_update = OrderedDict()
        items_to_add = []
        store = modulestore()
        src_block_to_dst_block = {}
        dst_block_ids = []
        dst_block_ids_has_children = []
        items_to_remove = []
        src_modules_ids = []

        # try to find main dst block to publish
        # (block in the "dst_course_id" course that corresponding to "source_usage_id")
        source_main_block_info = ApiBlockInfo.objects.filter(
            block_id=str(source_usage_id), course_id=course_id, has_children=True, deleted=False).first()
        if not source_main_block_info:
            return

        dst_main_block_info = ApiBlockInfo.objects.filter(
            hash_id=source_main_block_info.hash_id, course_id=dst_course_id, deleted=False).first()
        if not dst_main_block_info:
            return

        dst_main_block_id = dst_main_block_info.block_id
        sibling_update_task.sibling_block_id = dst_main_block_id

        last_published_version = get_last_published_course_version(dst_course_key)
        sibling_update_task.sibling_block_prev_version = last_published_version
        sibling_update_task.save()

        with store.bulk_operations(source_course_key):
            source_item = modulestore().get_item(source_usage_key)
            for module in yield_dynamic_descriptor_descendants(source_item, user.id):
                src_modules_ids.append(str(module.location))
                src_block_info = ApiBlockInfo.objects.filter(
                    block_id=str(module.location), course_id=course_id, deleted=False).first()
                if src_block_info:
                    dst_block_info_data = ApiBlockInfo.objects.filter(
                        hash_id=src_block_info.hash_id, course_id=dst_course_id, deleted=False)
                    if len(dst_block_info_data):
                        for dst_block_info in dst_block_info_data:
                            items_to_update[dst_block_info.block_id] = module
                            src_block_to_dst_block[src_block_info.block_id] = dst_block_info.block_id
                            dst_block_ids.append(dst_block_info.block_id)
                            if dst_block_info.has_children:
                                dst_block_ids_has_children.append(dst_block_info.block_id)
                    else:
                        items_to_add.append(module)

        with store.bulk_operations(dst_course_key):
            for block_id, src_block in items_to_update.items():
                _copy_fields_from_one_xblock_to_other(store, src_block, block_id, user, save_xblock_fn)

            dst_block_remove_check = []
            dst_item = modulestore().get_item(UsageKey.from_string(dst_main_block_id))
            for dst_module in yield_dynamic_descriptor_descendants(dst_item, user.id):
                dst_module_location = str(dst_module.location)
                if dst_module_location not in dst_block_ids:
                    dst_block_remove_check.append(dst_module_location)

            if dst_block_remove_check:
                dst_blocks_info = ApiBlockInfo.objects.filter(
                    block_id__in=dst_block_remove_check, course_id=dst_course_id, deleted=False)
                for dst_block in dst_blocks_info:
                    removed_src_block_info = ApiBlockInfo.objects.filter(
                        hash_id=dst_block.hash_id, course_id=course_id).first()
                    if removed_src_block_info:
                        need_remove = False
                        if removed_src_block_info.deleted:
                            need_remove = True
                        elif removed_src_block_info.block_id not in src_modules_ids:
                            need_remove = True
                            removed_src_block_info.deleted = True
                            removed_src_block_info.updated_time = timezone.now()
                            removed_src_block_info.updated_by = user.id
                            removed_src_block_info.save()

                        if need_remove:
                            items_to_remove.append(dst_block.block_id)
                            dst_block_ids.append(dst_block.block_id)
                            if dst_block.has_children:
                                dst_block_ids_has_children.append(dst_block.block_id)

            if items_to_remove:
                for item_id_to_remove in items_to_remove:
                    dst_block_info = ApiBlockInfo.objects.filter(
                        block_id=item_id_to_remove, course_id=dst_course_id, deleted=False).first()
                    if dst_block_info:
                        try:
                            delete_xblock_fn(UsageKey.from_string(item_id_to_remove), user)
                        except ItemNotFoundError:
                            pass

            if items_to_add:
                for category in ('sequential', 'vertical', 'other'):
                    for src_block in items_to_add:
                        if (src_block.category == 'sequential' and category == 'sequential')\
                          or (src_block.category == 'vertical' and category == 'vertical')\
                          or (src_block.category not in ('sequential', 'vertical') and category == 'other'):
                            src_block_parent = str(src_block.parent)
                            dst_block_parent = src_block_to_dst_block.get(src_block_parent)
                            if dst_block_parent:
                                duplicate_xblock_fn(
                                    UsageKey.from_string(dst_block_parent), src_block.location, user,
                                    src_block.display_name, course_key=dst_course_key, force_create_api_block_info=True)

            if need_publish:
                store.publish(UsageKey.from_string(dst_main_block_id), user_id)

        if dst_block_ids_has_children:
            SiblingBlockNotUpdated.objects.filter(
                source_course_id=course_id,
                sibling_block_id__in=dst_block_ids_has_children).delete()

        sibling_update_task.set_finished()
        sibling_update_task.save()
    except Exception as e:
        log.exception(e)
        sibling_update_task.set_error()
        sibling_update_task.save()
        raise


def get_all_descendants_block_ids(xblock, user):
    blocks_ids = []
    for module in yield_dynamic_descriptor_descendants(xblock, user.id):
        blocks_ids.append(str(module.location))
    return blocks_ids


def sync_api_block_info(xblock, prev_descendants_block_ids, user):
    all_block_ids = []
    api_block_ids = []
    current_blocks_ids = []
    xblocks = {}

    course_key = xblock.location.course_key
    course_id = str(course_key)

    if prev_descendants_block_ids:
        all_block_ids = prev_descendants_block_ids[:]

    for module in yield_dynamic_descriptor_descendants(xblock, user.id):
        module_id = str(module.location)
        current_blocks_ids.append(module_id)
        if module_id not in all_block_ids:
            all_block_ids.append(module_id)
        xblocks[module_id] = module

    block_info_data = ApiBlockInfo.objects.filter(course_id=course_id, block_id__in=all_block_ids)

    for block_info in block_info_data:
        api_block_ids.append(block_info.block_id)
        if (block_info.block_id not in current_blocks_ids) and not block_info.deleted:
            block_info.deleted = True
            block_info.updated_by = user.id
            block_info.updated_time = timezone.now()
            block_info.save()
        if (block_info.block_id in current_blocks_ids) and block_info.deleted:
            block_info.deleted = False
            block_info.updated_by = user.id
            block_info.updated_time = timezone.now()
            block_info.save()

    for module_id, module in xblocks.items():
        if module_id not in api_block_ids:
            block_hash_id = str(uuid4())
            api_block_info = ApiBlockInfo(
                course_id=course_id,
                block_id=module_id,
                hash_id=block_hash_id,
                created_by=user.id,
                created_time=timezone.now()
            )
            api_block_info.set_has_children()
            api_block_info.save()


def get_courses_with_duplicates(usage_key_string, user):
    usage_key = UsageKey.from_string(usage_key_string)
    result_course_keys = []
    result = []

    src_block_info = ApiBlockInfo.objects.filter(block_id=usage_key_string, has_children=True, deleted=False).first()
    if src_block_info and (not src_block_info.created_as_copy
                           or (src_block_info.created_as_copy and src_block_info.published_after_copy)):
        courses = ApiBlockInfo.objects.filter(hash_id=src_block_info.hash_id, deleted=False) \
            .exclude(course_id=str(usage_key.course_key)).values('course_id').distinct()
        for course in courses:
            tmp_course_key = CourseKey.from_string(course['course_id'])
            if has_studio_write_access(user, tmp_course_key):
                result_course_keys.append(tmp_course_key)

    if result_course_keys:
        co_data = CourseOverview.objects.filter(id__in=result_course_keys).order_by('display_name')
        for co_item in co_data:
            result.append({
                'id': str(co_item.id),
                'display_name': co_item.display_name,
                'org': co_item.id.org,
                'course': co_item.id.course,
                'run': co_item.id.run
            })
    return result


def sync_api_blocks_before_remove(usage_key, user):
    block_info_update_lst = []
    deleted_module = modulestore().get_item(usage_key)
    if deleted_module.has_children:
        for module in yield_dynamic_descriptor_descendants(deleted_module, user.id):
            block_info_update_lst.append(str(module.location))
    else:
        block_info_update_lst.append(str(usage_key))
    if block_info_update_lst:
        ApiBlockInfo.objects.filter(block_id__in=block_info_update_lst).update(
            deleted=True, updated_time=timezone.now(), updated_by=user.id)


class SyncApiBlockInfo(object):
    xblock = None
    user = None
    descendants_block_ids = None

    def __init__(self, xblock, user):
        self.xblock = xblock
        self.user = user

    def __enter__(self):
        self.descendants_block_ids = get_all_descendants_block_ids(self.xblock, self.user)

    def __exit__(self, *args):
        xblock_after_change = modulestore().get_item(self.xblock.location)
        sync_api_block_info(xblock_after_change, self.descendants_block_ids, self.user)
