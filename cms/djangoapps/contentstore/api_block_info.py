import json
import hashlib
import logging
import time
from uuid import uuid4
from collections import OrderedDict

from celery import shared_task
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.contrib.auth import get_user_model
from django.utils import timezone
from common.djangoapps.util.module_utils import yield_dynamic_descriptor_descendants
from openedx.core.djangoapps.content.block_structure.models import ApiBlockInfo, ApiBlockInfoNotSiblings
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview
from opaque_keys.edx.keys import CourseKey, UsageKey
from common.djangoapps.credo_modules.mongo import get_last_published_course_version,\
    get_versions_for_blocks
from common.djangoapps.credo_modules.models import SiblingBlockUpdateTask
from common.djangoapps.student.auth import has_studio_write_access
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.exceptions import ItemNotFoundError
from xmodule.library_tools import LibraryToolsService
from xmodule.modulestore.inheritance import get_settings_data
from xblock.fields import Scope
from milestones.models import Milestone, CourseContentMilestone


User = get_user_model()
log = logging.getLogger(__name__)


class CopyInfoEntry:
    data = None
    metadata = None
    fields = None
    tags = None
    asides_to_update = None

    def __init__(self, xblock):
        self.metadata = {}
        self.fields = {}

        for field in xblock.fields.values():
            if field.scope == Scope.settings and field.is_set_on(xblock):
                self.metadata[field.name] = field.read_from(xblock)
            if field.scope == Scope.content and field.is_set_on(xblock):
                self.fields[field.name] = field.read_from(xblock)

        self.data = getattr(xblock, 'data', None)
        if self.data and not isinstance(self.data, str):
            self.data = None

        self.asides_to_update = None
        self.tags = {}
        for aside in xblock.runtime.get_asides(xblock):
            if aside.scope_ids.block_type in ('tagging_aside', 'tagging_ora_aside') and aside.saved_tags:
                self.asides_to_update = [aside]
                self.tags = aside.get_sorted_tags()
                break


def create_api_block_info(usage_key, user, block_hash_id=None, created_as_copy=False,
                          created_as_copy_from_course_id=None, published_after_copy=False, auto_save=True,
                          published_content_version=None):
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
        created_as_copy_from_course_id=created_as_copy_from_course_id,
        published_after_copy=published_after_copy,
        published_content_version=published_content_version,
    )
    api_block_info.set_has_children()
    if auto_save:
        api_block_info.save()
    return api_block_info


def copy_api_block_info(source_item, dest_module, user, level=0, auto_save=True, force=False,
                        published_after_copy=False):
    src_course_id = str(source_item.location.course_key)
    dst_course_id = str(dest_module.location.course_key)

    published_content_version = None

    if source_item.category == 'vertical' and published_after_copy:
        published_content_version = get_content_version(source_item)

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
                    source_block_info = create_api_block_info(
                        source_item.location, user, published_content_version=published_content_version
                    )
                    source_block_hash = source_block_info.hash_id
        except IntegrityError:
            source_block_info = ApiBlockInfo.objects.filter(block_id=str(source_item.location)).first()
            if source_block_info:
                source_block_hash = source_block_info.hash_id

    if source_item.category == 'vertical':
        not_siblings = ApiBlockInfoNotSiblings.objects.filter(
            Q(source_block_id=str(source_item.location)) | Q(dst_block_id=str(source_item.location)))
        for not_sibling in not_siblings:
            other_block_id = not_sibling.source_block_id if not_sibling.dst_block_id == str(source_item.location) else not_sibling.dst_block_id
            ApiBlockInfoNotSiblings(
                source_course_id=str(UsageKey.from_string(other_block_id).course_key),
                source_block_id=other_block_id,
                dst_block_id=str(dest_module.location),
                dst_course_id=str(UsageKey.from_string(str(dest_module.location)).course_key),
                user_id=user.id
            ).save()

    return create_api_block_info(dest_module.location, user,
                                 block_hash_id=source_block_hash,
                                 created_as_copy=True,
                                 created_as_copy_from_course_id=src_course_id,
                                 published_after_copy=published_after_copy,
                                 auto_save=auto_save,
                                 published_content_version=published_content_version)


def update_api_blocks_before_publish(xblock, user):
    block_id = str(xblock.location)
    course_id = str(xblock.location.course_key)
    api_block_info = ApiBlockInfo.objects.filter(
        course_id=course_id, block_id=block_id, deleted=False).first()

    if api_block_info:
        if api_block_info.has_children:
            block_ids = []
            vertical_blocks = []
            for module in yield_dynamic_descriptor_descendants(xblock, user.id):
                block_ids.append(str(module.location))
                if module.category == 'vertical':
                    vertical_blocks.append(module)
            if vertical_blocks:
                check_connection_between_siblings(user, course_id, vertical_blocks)
            ApiBlockInfo.objects.filter(course_id=course_id, block_id__in=block_ids, deleted=False)\
                .update(published_after_copy=True, created_as_copy_from_course_id=None)
        else:
            api_block_info.created_as_copy_from_course_id = None
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


def check_and_restore_sibling_conection(block_id, block_hash_id, content_version):
    not_sibling_blocks = ApiBlockInfoNotSiblings.objects.filter(Q(source_block_id=block_id) | Q(dst_block_id=block_id))
    for block in not_sibling_blocks:
        related_block_id = block.source_block_id if block.dst_block_id == block_id else block.dst_block_id
        not_sibling_block = ApiBlockInfo.objects.filter(
            hash_id=block_hash_id, block_id=related_block_id, published_content_version=content_version).first()
        if not_sibling_block:
            ApiBlockInfoNotSiblings.objects.filter(
                Q(source_block_id=block_id, dst_block_id=related_block_id)
                | Q(source_block_id=related_block_id, dst_block_id=block_id)).delete()


def update_sibling_block_after_publish(related_courses, xblock, user, vertical_ids_with_changes):
    task_uuid = str(uuid4())
    course_ids_without_changes = []
    course_id = str(xblock.location.course_key)

    for module in yield_dynamic_descriptor_descendants(xblock, user.id):
        if module.category == 'vertical':
            content_version = get_content_version(module)
            block_id = str(module.location)
            src_api_blocks_info = ApiBlockInfo.objects.filter(
                block_id=block_id, deleted=False).first()
            if src_api_blocks_info:
                src_api_blocks_info.published_content_version = content_version
                src_api_blocks_info.save()

                # restore connection between siblings
                if src_api_blocks_info.reverted_to_previous_version:
                    src_api_blocks_info.reverted_to_previous_version = False
                    src_api_blocks_info.save()
                check_and_restore_sibling_conection(block_id, src_api_blocks_info.hash_id, content_version)

    course_ids_updated = [course_id]
    if xblock.category in ApiBlockInfo.CATEGORY_HAS_CHILDREN:
        update_res = []
        if related_courses:
            for related_course_id, course_action in related_courses.items():
                if course_action in ('publish', 'draft'):
                    course_ids_updated.append(related_course_id)
                    if has_studio_write_access(user, CourseKey.from_string(related_course_id)):
                        with transaction.atomic():
                            sibling_block_update_task = SiblingBlockUpdateTask(
                                task_id=task_uuid,
                                initiator=user,
                                source_course_id=course_id,
                                source_block_id=str(xblock.location),
                                sibling_course_id=str(related_course_id),
                                published=bool(course_action == 'publish')
                            )
                            sibling_block_update_task.save()
                            update_res.append((sibling_block_update_task.id, related_course_id, course_action))
                else:
                    course_ids_without_changes.append(related_course_id)

        # break connection between siblings
        if course_ids_without_changes:
            not_siblings_list = []

            src_blocks_tmp = ApiBlockInfo.objects.filter(
                block_id__in=vertical_ids_with_changes, deleted=False)
            hashes_tmp = [src_block.hash_id for src_block in src_blocks_tmp]
            src_related_blocks = ApiBlockInfo.objects.filter(
                hash_id__in=hashes_tmp, course_id__in=course_ids_updated, deleted=False)
            for src_item in src_related_blocks:
                for course_id_without_changes in course_ids_without_changes:
                    dst_block = ApiBlockInfo.objects.filter(course_id=course_id_without_changes, hash_id=src_item.hash_id,
                                                            deleted=False).first()
                    if not dst_block:
                        continue
                    b1 = ApiBlockInfoNotSiblings.objects.filter(source_block_id=src_item.block_id,
                                                                dst_block_id=dst_block.block_id).first()
                    if b1:
                        continue
                    b2 = ApiBlockInfoNotSiblings.objects.filter(source_block_id=dst_block.block_id,
                                                                dst_block_id=src_item.block_id).first()
                    if b2:
                        continue

                    not_siblings_list.append(ApiBlockInfoNotSiblings(
                        source_block_id=src_item.block_id,
                        source_course_id=str(UsageKey.from_string(src_item.block_id).course_key),
                        dst_block_id=dst_block.block_id,
                        dst_course_id=str(UsageKey.from_string(dst_block.block_id).course_key),
                        user_id=user.id
                    ))

            if not_siblings_list:
                ApiBlockInfoNotSiblings.objects.bulk_create(not_siblings_list, 1000)

        def process_on_commit():
            if update_res:
                for task_id, rel_course_id, rel_course_action in update_res:
                    update_sibling_block_in_related_course.delay(
                        task_id, str(xblock.location), rel_course_id, rel_course_action == 'publish', user.id)

        transaction.on_commit(process_on_commit)
        if update_res:
            return task_uuid
    return None


def _copy_fields_from_one_xblock_to_other(store, source_block, dst_block_id, user, save_xblock_fn, lib_tools=None):
    dst_item = store.get_item(UsageKey.from_string(dst_block_id))

    source_block_info = CopyInfoEntry(source_block)
    dst_block_info = CopyInfoEntry(dst_item)

    # Don't update chapter/sequential blocks
    if source_block.location.block_type in ('chapter', 'sequential'):
        return

    update_library_content = False
    if lib_tools and source_block.location.block_type == 'library_content'\
      and source_block.source_library_version != dst_item.source_library_version:
        update_library_content = True

    need_update = False
    if source_block_info.metadata != dst_block_info.metadata\
      or source_block_info.fields != dst_block_info.fields\
      or source_block_info.data != dst_block_info.data\
      or source_block_info.tags != dst_block_info.tags:
        need_update = True

    if need_update:
        save_xblock_fn(user, dst_item,
                       data=source_block_info.data,
                       metadata=source_block_info.metadata,
                       fields=source_block_info.fields,
                       asides=source_block_info.asides_to_update)
        if update_library_content:
            lib_tools.update_children(dst_item, version=source_block.source_library_version,
                                      check_permissions=False)


def get_versions_info_data(course_id, block_ids, course_version=None):
    res = {}
    versions_info = get_versions_for_blocks(course_id, block_ids, course_version_id=course_version)
    for usage_id, ver_data in versions_info.items():
        for var_item in ver_data:
            if not var_item['can_restore']:
                res[usage_id] = var_item['id']
    return res


def _update_sibling_block_add_new_items(items_to_add, allowed_categories, src_block_to_dst_block, dst_course_key,
                                        user, published_after_copy, duplicate_xblock_fn):
    for category in allowed_categories:
        for src_block in items_to_add:
            if (src_block.category == 'sequential' and category == 'sequential') \
              or (src_block.category == 'vertical' and category == 'vertical') \
              or (src_block.category not in ('sequential', 'vertical') and category == 'other'):
                src_block_parent = str(src_block.parent)
                dst_block_parent_lst = src_block_to_dst_block.get(src_block_parent)
                if dst_block_parent_lst:
                    for dst_block_parent in dst_block_parent_lst:
                        duplicate_xblock_fn(
                            UsageKey.from_string(dst_block_parent), src_block.location, user,
                            src_block.display_name, course_key=dst_course_key, force_create_api_block_info=True,
                            published_after_copy=published_after_copy)


def _get_sibling_not_connected(source_item, source_course_id, dst_course_id, user):
    sibling_not_connected = []

    for module in yield_dynamic_descriptor_descendants(source_item, user.id):
        if module.category == 'vertical':
            src_block_info = ApiBlockInfo.objects.filter(
                block_id=str(module.location), course_id=source_course_id).first()
            if src_block_info:
                dst_block_info_data = ApiBlockInfo.objects.filter(
                    hash_id=src_block_info.hash_id, course_id=dst_course_id)
                if len(dst_block_info_data):
                    for dst_block_info in dst_block_info_data:
                        block_to_check_1 = src_block_info.block_id
                        block_to_check_2 = dst_block_info.block_id
                        not_siblings = _check_blocks_not_siblings(block_to_check_1, block_to_check_2)
                        if not_siblings:
                            sibling_not_connected.append(src_block_info.block_id)
                            for child in module.get_children():
                                sibling_not_connected.append(str(child.location))
    return sibling_not_connected


def _check_blocks_not_siblings(block_to_check_1, block_to_check_2):
    not_siblings = False
    b1 = ApiBlockInfoNotSiblings.objects.filter(
        source_block_id=block_to_check_1, dst_block_id=block_to_check_2).first()
    if b1:
        not_siblings = True
    else:
        b2 = ApiBlockInfoNotSiblings.objects.filter(
            source_block_id=block_to_check_2, dst_block_id=block_to_check_1).first()
        if b2:
            not_siblings = True
    return not_siblings


@shared_task()
def update_sibling_block_in_related_course(task_id, source_usage_id, dst_course_id, need_publish, user_id):
    try:
        sibling_update_task = SiblingBlockUpdateTask.objects.get(id=task_id)
    except SiblingBlockUpdateTask.DoesNotExist:
        return

    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        log.exception("update_sibling_block: user not found", user_id)
        sibling_update_task.set_error()
        sibling_update_task.save()
        return

    try:
        sibling_update_task.set_started()
        sibling_update_task.save()

        res = _update_sibling_block_in_related_course(source_usage_id, dst_course_id, need_publish, user,
                                                      sibling_update_task=sibling_update_task)

        if res:
            sibling_update_task.set_finished()
            sibling_update_task.save()
        else:
            sibling_update_task.set_error()
            sibling_update_task.save()
    except Exception as e:
        log.exception(e)
        sibling_update_task.set_error()
        sibling_update_task.save()
        raise


def _update_sibling_block_in_related_course(source_usage_id, dst_course_id, need_publish, user, sibling_update_task=None):
    from .views.item import _save_xblock as save_xblock_fn, _delete_item as delete_xblock_fn,\
        _duplicate_item as duplicate_xblock_fn

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
        log.exception("update_sibling_block: src block not found", str(source_usage_id))
        return False

    dst_main_block_info = ApiBlockInfo.objects.filter(
        hash_id=source_main_block_info.hash_id, course_id=dst_course_id, deleted=False).first()
    if not dst_main_block_info:
        log.exception("update_sibling_block: corresponding block not found", str(source_usage_id))
        return False

    all_dst_blocks = ApiBlockInfo.objects.filter(hash_id=source_main_block_info.hash_id, course_id=dst_course_id,
                                                 deleted=False)

    dst_main_block_id = dst_main_block_info.block_id
    if sibling_update_task:
        sibling_update_task.sibling_block_id = dst_main_block_id

        last_published_version = get_last_published_course_version(dst_course_key)
        sibling_update_task.sibling_block_prev_version = last_published_version
        sibling_update_task.save()

    vertical_blocks = []

    with store.bulk_operations(source_course_key):
        source_item = modulestore().get_item(source_usage_key)
        sibling_src_not_connected = _get_sibling_not_connected(source_item, course_id, dst_course_id, user)

        for module in yield_dynamic_descriptor_descendants(source_item, user.id):
            src_modules_ids.append(str(module.location))
            if str(module.location) in sibling_src_not_connected:
                continue
            src_block_info = ApiBlockInfo.objects.filter(
                block_id=str(module.location), course_id=course_id, deleted=False).first()
            if module.category == 'vertical' and src_block_info.published_content_version:
                vertical_blocks.append({
                    "block_id": str(module.location),
                    "published_content_version": src_block_info.published_content_version,
                    "hash_id": src_block_info.hash_id
                })
            if src_block_info:
                dst_block_info_data = ApiBlockInfo.objects.filter(
                    hash_id=src_block_info.hash_id, course_id=dst_course_id)
                if len(dst_block_info_data):
                    for dst_block_info in dst_block_info_data:
                        if dst_block_info.deleted:
                            continue

                        if dst_block_info.reverted_to_previous_version:
                            dst_block_info.reverted_to_previous_version = False
                            dst_block_info.save(update_fields=['reverted_to_previous_version'])
                        if need_publish and src_block_info.published_content_version:
                            dst_block_info.published_content_version = src_block_info.published_content_version
                            dst_block_info.save(update_fields=['published_content_version'])

                        items_to_update[dst_block_info.block_id] = module
                        if src_block_info.block_id not in src_block_to_dst_block:
                            src_block_to_dst_block[src_block_info.block_id] = []
                        src_block_to_dst_block[src_block_info.block_id].append(dst_block_info.block_id)
                        dst_block_ids.append(dst_block_info.block_id)
                        if dst_block_info.has_children:
                            dst_block_ids_has_children.append(dst_block_info.block_id)
                else:
                    items_to_add.append(module)

    store = modulestore()
    lib_tools = LibraryToolsService(store, user.id)

    with store.bulk_operations(dst_course_key):
        for block_id, src_block in items_to_update.items():
            _copy_fields_from_one_xblock_to_other(store, src_block, block_id, user, save_xblock_fn,
                                                  lib_tools=lib_tools)
        if items_to_update:
            if need_publish:
                ApiBlockInfo.objects.filter(
                    course_id=dst_course_id, block_id__in=list(items_to_update.keys()), deleted=False
                ).update(
                    created_as_copy=True, created_as_copy_from_course_id=course_id,
                    published_after_copy=True
                )
            else:
                ApiBlockInfo.objects.filter(
                    course_id=dst_course_id, block_id__in=list(items_to_update.keys()), deleted=False
                ).update(
                    created_as_copy=True, created_as_copy_from_course_id=course_id,
                    published_after_copy=False
                )

        dst_block_remove_check = []

        for some_dst_block in all_dst_blocks:
            some_dst_block_id = str(some_dst_block.block_id)
            dst_item = modulestore().get_item(UsageKey.from_string(some_dst_block_id))
            sibling_dst_not_connected = _get_sibling_not_connected(dst_item, dst_course_id, course_id, user)

            for dst_module in yield_dynamic_descriptor_descendants(dst_item, user.id):
                dst_module_location = str(dst_module.location)
                if dst_module_location not in dst_block_ids:
                    if dst_module_location not in sibling_dst_not_connected:
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
                        try:
                            removed_src_block_info_key = UsageKey.from_string(removed_src_block_info.block_id)
                            modulestore().get_item(removed_src_block_info_key)
                        except ItemNotFoundError:
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
            _update_sibling_block_add_new_items(
                items_to_add, ['vertical', 'other'], src_block_to_dst_block, dst_course_key, user,
                published_after_copy=need_publish, duplicate_xblock_fn=duplicate_xblock_fn)

        if need_publish:
            for some_dst_block in all_dst_blocks:
                some_dst_block_id = str(some_dst_block.block_id)
                store.publish(UsageKey.from_string(some_dst_block_id), user.id)

        if items_to_add:
            _update_sibling_block_add_new_items(
                items_to_add, ['sequential'], src_block_to_dst_block, dst_course_key, user,
                published_after_copy=False, duplicate_xblock_fn=duplicate_xblock_fn)

        if need_publish:
            for vert_block in vertical_blocks:
                ApiBlockInfo.objects.filter(
                    course_id=dst_course_id, hash_id=vert_block['hash_id'], deleted=False).update(
                    published_after_copy=True,
                    published_content_version=vert_block['published_content_version']
                )
    return True


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
    hash_ids = []

    src_block_info = ApiBlockInfo.objects.filter(block_id=usage_key_string, has_children=True, deleted=False).first()

    if src_block_info and (not src_block_info.created_as_copy
                           or (src_block_info.created_as_copy and src_block_info.published_after_copy)):
        non_published_vertical_block_ids = get_non_published_vertical_blocks(usage_key_string, user)

        if non_published_vertical_block_ids and usage_key.block_type in ('chapter', 'sequential'):

            courses = ApiBlockInfo.objects.filter(hash_id=src_block_info.hash_id, deleted=False) \
                .exclude(course_id=str(usage_key.course_key)).values('course_id').distinct()
            for course in courses:
                tmp_course_key = CourseKey.from_string(course['course_id'])
                if has_studio_write_access(user, tmp_course_key):
                    result_course_keys.append(tmp_course_key)

        else:
            vertical_block_ids = get_vertical_blocks_with_changes(usage_key_string, user)

            block_ids_to_exclude = []

            if vertical_block_ids:
                vertical_blocks = ApiBlockInfo.objects.filter(
                    block_id__in=vertical_block_ids, has_children=True, deleted=False)
                for v_block in vertical_blocks:
                    if not v_block.created_as_copy or (v_block.created_as_copy and v_block.published_after_copy):
                        hash_ids.append(v_block.hash_id)

                blocks_no_siblings1 = ApiBlockInfoNotSiblings.objects.filter(source_block_id__in=vertical_block_ids)
                for b in blocks_no_siblings1:
                    if b.dst_block_id not in block_ids_to_exclude:
                        block_ids_to_exclude.append(b.dst_block_id)

                blocks_no_siblings2 = ApiBlockInfoNotSiblings.objects.filter(dst_block_id__in=vertical_block_ids)
                for b in blocks_no_siblings2:
                    if b.source_block_id not in block_ids_to_exclude:
                        block_ids_to_exclude.append(b.source_block_id)

            exclude_expr = Q(course_id=str(usage_key.course_key))
            if block_ids_to_exclude:
                exclude_expr = Q(course_id=str(usage_key.course_key)) | Q(block_id__in=block_ids_to_exclude)

            if hash_ids:
                courses = ApiBlockInfo.objects.filter(hash_id__in=hash_ids, deleted=False) \
                    .exclude(exclude_expr).values('course_id')\
                    .distinct()

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


def _sync_api_blocks_remove(xblock, user):
    block_info_update_lst = []
    usage_id = str(xblock.location)
    if xblock.has_children:
        for module in yield_dynamic_descriptor_descendants(xblock, user.id):
            block_info_update_lst.append(str(module.location))
    else:
        block_info_update_lst.append(usage_id)
    if block_info_update_lst:
        ApiBlockInfo.objects.filter(block_id__in=block_info_update_lst).update(
            deleted=True, updated_time=timezone.now(), updated_by=user.id)


def sync_api_blocks_before_remove(usage_key, user):
    deleted_module = modulestore().get_item(usage_key)
    _sync_api_blocks_remove(deleted_module, user)


def sync_api_blocks_before_move(usage_key, user):
    api_blocks_to_insert = []
    course_key = usage_key.course_key
    xblock = modulestore().get_item(usage_key)
    if xblock.has_children:
        for module in yield_dynamic_descriptor_descendants(xblock, user.id):
            api_block = ApiBlockInfo.objects.filter(
                course_id=str(course_key), block_id=str(module.location), deleted=False).first()
            if api_block:
                api_block.block_id = api_block.block_id + '-del-' + str(int(time.time()))
                api_block.updated_time = timezone.now()
                api_block.updated_by = user.id
                api_block.deleted = True
                api_block.save()
                api_blocks_to_insert.append(
                    create_api_block_info(module.location, user, auto_save=False)
                )
    if api_blocks_to_insert:
        ApiBlockInfo.objects.bulk_create(api_blocks_to_insert, 1000)


def update_api_block_info(xblock, user, reverted_to_previous_version=False):
    api_block_info = ApiBlockInfo.objects.filter(block_id=str(xblock.location), deleted=False).first()
    if api_block_info:
        api_block_info.reverted_to_previous_version = reverted_to_previous_version
        api_block_info.save(update_fields=['reverted_to_previous_version'])


def get_vertical_blocks_with_changes(usage_id, user):
    xblock = modulestore().get_item(UsageKey.from_string(usage_id))
    result = []

    for module in yield_dynamic_descriptor_descendants(xblock, user.id):
        if module.category == 'vertical' and modulestore().has_changes(module):
            result.append(str(module.location))
    return result


def get_non_published_vertical_blocks(usage_id, user):
    xblock = modulestore().get_item(UsageKey.from_string(usage_id))
    result = []

    for module in yield_dynamic_descriptor_descendants(xblock, user.id):
        if module.category == 'vertical' and not modulestore().has_published_version(module):
            result.append(str(module.location))
    return result


def check_connection_between_siblings(user, course_id, vertical_xblocks):
    for vertical_xblock in vertical_xblocks:
        src_block_id = str(vertical_xblock.location)
        api_block_info = ApiBlockInfo.objects.filter(course_id=course_id, block_id=src_block_id, deleted=False).first()
        if not api_block_info or (not api_block_info.created_as_copy
                                  or (api_block_info.created_as_copy and api_block_info.published_after_copy)):
            return

        xblock_content_version = get_content_version(vertical_xblock)
        api_block_info.published_content_version = xblock_content_version
        api_block_info.save()

        if api_block_info.created_as_copy_from_course_id:
            related_block_info = ApiBlockInfo.objects.filter(
                course_id=api_block_info.created_as_copy_from_course_id,
                hash_id=api_block_info.hash_id
            ).first()
        else:
            # fallback
            related_block_info = ApiBlockInfo.objects.filter(
                hash_id=api_block_info.hash_id, published_after_copy=False, deleted=False)\
                .exclude(block_id=src_block_id).first()

        if related_block_info:
            not_siblings = ApiBlockInfoNotSiblings.objects.filter(
                Q(source_block_id=src_block_id, dst_block_id=related_block_info.block_id)
                |
                Q(dst_block_id=src_block_id, source_block_id=related_block_info.block_id)
            ).first()
            if not_siblings:
                return

            if related_block_info.published_content_version:
                related_block_content_version = related_block_info.published_content_version
            else:
                with modulestore().branch_setting(ModuleStoreEnum.Branch.published_only):
                    xblock_item = modulestore().get_item(UsageKey.from_string(related_block_info.block_id))
                    related_block_content_version = get_content_version(xblock_item)

            if xblock_content_version != related_block_content_version:
                # break connection with ALL related blocks (not only "created_as_copy_from_course_id")
                related_blocks = ApiBlockInfo.objects.filter(
                    hash_id=related_block_info.hash_id
                ).exclude(course_id=course_id)
                for rel_block in related_blocks:
                    not_siblings = ApiBlockInfoNotSiblings.objects.filter(
                        Q(source_block_id=src_block_id, dst_block_id=rel_block.block_id)
                        |
                        Q(dst_block_id=src_block_id, source_block_id=rel_block.block_id)
                    ).first()
                    if not not_siblings:
                        not_siblings = ApiBlockInfoNotSiblings(
                            source_course_id=str(UsageKey.from_string(src_block_id).course_key),
                            source_block_id=src_block_id,
                            dst_course_id=str(UsageKey.from_string(rel_block.block_id).course_key),
                            dst_block_id=rel_block.block_id,
                            user_id=user.id
                        )
                        not_siblings.save()


def get_content_version(vertical_xblock):
    hashes_lst = []
    exclude_metadata_keys = ['graceperiod', 'xml_attributes', 'xqa_key', 'start', 'due', 'user_partitions']
    if vertical_xblock.category == 'vertical':
        for child_xblock in vertical_xblock.get_children():
            metadata = get_settings_data(child_xblock)
            for k in exclude_metadata_keys:
                if k in metadata:
                    metadata.pop(k, None)
            fields = child_xblock.get_explicitly_set_fields_by_scope(Scope.content)
            metadata_str = json.dumps(metadata, sort_keys=True, default=str)
            fields_str = json.dumps(fields, sort_keys=True, default=str)
            tags_str = ""
            for aside in child_xblock.runtime.get_asides(child_xblock):
                if aside.scope_ids.block_type in ('tagging_aside', 'tagging_ora_aside') and aside.saved_tags:
                    tags_str = "_" + json.dumps(aside.saved_tags, sort_keys=True, default=str)

            data = metadata_str + '_' + fields_str + tags_str
            hashes_lst.append(data)
        big_hash = '_'.join(hashes_lst)
        return hashlib.md5(big_hash.encode('utf-8')).hexdigest()
    return None


def copy_milestones(src_course_id, dst_course_id):
    src_course_key = CourseKey.from_string(src_course_id)
    str_token = f'{src_course_key.org}+{src_course_key.course}+{src_course_key.run}'
    milestones = Milestone.objects.filter(namespace__icontains=str_token)
    milestone_dict = {}
    for milestone in milestones:
        block_id = milestone.namespace.split('.')[0]
        ending = milestone.namespace.split('.')[1]
        src_block = ApiBlockInfo.objects.filter(course_id=src_course_id, block_id=block_id).first()
        if not src_block:
            continue
        dst_block = ApiBlockInfo.objects.filter(course_id=dst_course_id, hash_id=src_block.hash_id,
                                                deleted=False).first()
        if not dst_block:
            continue
        dst_milestone_namespace = dst_block.block_id + '.' + ending
        dst_milestone_name = milestone.name.replace(block_id, dst_block.block_id)

        dst_milestone = Milestone.objects.filter(namespace=dst_milestone_namespace, name=dst_milestone_name).first()
        if not dst_milestone:
            dst_milestone = Milestone(
                namespace=dst_milestone_namespace,
                name=dst_milestone_name,
                display_name=milestone.display_name,
                description=milestone.description,
                active=milestone.active
            )
            dst_milestone.save()
        milestone_dict[milestone.id] = dst_milestone.id

    dst_content_milestone_lst = []
    content_milestones = CourseContentMilestone.objects.filter(course_id=src_course_id)
    for content_milestone in content_milestones:
        src_block = ApiBlockInfo.objects.filter(course_id=src_course_id, block_id=content_milestone.content_id).first()
        if not src_block:
            continue
        dst_block = ApiBlockInfo.objects.filter(course_id=dst_course_id, hash_id=src_block.hash_id, deleted=False).first()
        if not dst_block:
            continue

        dst_milestone_id = milestone_dict.get(content_milestone.milestone_id)
        dst_content_milestone = CourseContentMilestone.objects.filter(
            course_id=dst_course_id, content_id=dst_block.block_id).first()
        if not dst_content_milestone and dst_milestone_id:
            dst_content_milestone_lst.append(
                CourseContentMilestone(
                    course_id=dst_course_id,
                    content_id=dst_block.block_id,
                    milestone_id=dst_milestone_id,
                    milestone_relationship_type_id=content_milestone.milestone_relationship_type_id,
                    requirements=content_milestone.requirements,
                    active=content_milestone.active
                )
            )

    if dst_content_milestone_lst:
        CourseContentMilestone.objects.bulk_create(dst_content_milestone_lst)


class SyncApiBlockInfo:
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
