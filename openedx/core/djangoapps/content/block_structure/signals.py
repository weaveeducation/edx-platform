"""
Signal handlers for invalidating cached data.
"""

import logging

from django.conf import settings
from django.dispatch.dispatcher import receiver
from django.utils import timezone
from opaque_keys.edx.locator import LibraryLocator

from xmodule.modulestore.django import SignalHandler, modulestore
from xmodule.modulestore import ModuleStoreEnum
from xmodule.modulestore.exceptions import ItemNotFoundError

from . import config
from .api import clear_course_from_cache
from .models import ApiCourseStructureLock, BlockStructureNotFound
from .tasks import update_course_in_cache_v2, update_course_structure

log = logging.getLogger(__name__)


@receiver(SignalHandler.course_published)
def update_block_structure_on_course_publish(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Catches the signal that a course has been published in the module
    store and creates/updates the corresponding cache entry.
    Ignores publish signals from content libraries.
    """
    if isinstance(course_key, LibraryLocator):
        return

    if config.INVALIDATE_CACHE_ON_PUBLISH.is_enabled():
        try:
            clear_course_from_cache(course_key)
        except BlockStructureNotFound:
            log.warning(
                "BlockStructure: %s not found when trying to clear course from cache",
                course_key,
            )

    update_course_in_cache_v2.apply_async(
        kwargs=dict(course_id=str(course_key)),
        countdown=settings.BLOCK_STRUCTURES_SETTINGS['COURSE_PUBLISH_TASK_DELAY'],
    )

    with modulestore().branch_setting(ModuleStoreEnum.Branch.published_only):
        try:
            course = modulestore().get_course(course_key)
            course_id = str(course_key)
            if course_id and course_id.startswith('course-v1'):
                if settings.DEBUG:
                    update_course_structure(course_id)
                else:
                    lock_result = ApiCourseStructureLock(
                        course_id=course_id,
                        created=timezone.now(),
                        task_id=None,
                        published_on=str(course.published_on)
                    )
                    lock_result.save()
        except ItemNotFoundError:
            pass


@receiver(SignalHandler.course_deleted)
def _delete_block_structure_on_course_delete(sender, course_key, **kwargs):  # pylint: disable=unused-argument
    """
    Catches the signal that a course has been deleted from the
    module store and invalidates the corresponding cache entry if one
    exists.
    """
    clear_course_from_cache(course_key)
