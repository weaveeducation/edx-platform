"""
Models used by the block structure framework.
"""


import json
import errno
from contextlib import contextmanager
from datetime import datetime
from logging import getLogger

from django.conf import settings
from django.core.exceptions import SuspiciousOperation
from django.core.files.base import ContentFile
from django.db import models, transaction, IntegrityError
from django.utils import timezone

from model_utils.models import TimeStampedModel

from openedx.core.djangoapps.xmodule_django.models import UsageKeyWithRunField
from openedx.core.storage import get_storage
from opaque_keys.edx.keys import CourseKey
from common.djangoapps.credo_modules.mongo import get_course_structure

from . import config
from .exceptions import BlockStructureNotFound

log = getLogger(__name__)


def _create_path(directory, filename):
    """
    Returns the full path for the given directory and filename.
    """
    return f'{directory}/{filename}'


def _directory_name(data_usage_key):
    """
    Returns the directory name for the given
    data_usage_key.
    """
    # .. setting_name: BLOCK_STRUCTURES_SETTINGS['DIRECTORY_PREFIX']
    # .. setting_default: ''
    # .. setting_description: Specifies the path in storage where block structures would be saved,
    #   for storage-backed block structure cache.
    #   For more information, check https://github.com/openedx/edx-platform/pull/14571.
    # .. setting_warnings: Depends on `BLOCK_STRUCTURES_SETTINGS['STORAGE_CLASS']` and on
    #   `block_structure.storage_backing_for_cache`.
    directory_prefix = settings.BLOCK_STRUCTURES_SETTINGS.get('DIRECTORY_PREFIX', '')

    # replace any '/' in the usage key so they aren't interpreted
    # as folder separators.
    encoded_usage_key = str(data_usage_key).replace('/', '_')
    return '{}{}'.format(
        directory_prefix,
        encoded_usage_key,
    )


def _path_name(bs_model, _filename):
    """
    Returns path name to use for the given
    BlockStructureModel instance.
    """
    filename = datetime.utcnow().strftime('%Y-%m-%d-%H:%M:%S-%f')
    return _create_path(
        _directory_name(bs_model.data_usage_key),
        filename,
    )


def _bs_model_storage():
    """
    Get django Storage object for BlockStructureModel.
    """
    # .. setting_name: BLOCK_STRUCTURES_SETTINGS['STORAGE_CLASS']
    # .. setting_default: None
    # .. setting_description: Specifies the storage used for storage-backed block structure cache.
    #   For more information, check https://github.com/openedx/edx-platform/pull/14571.
    # .. setting_warnings: Depends on `block_structure.storage_backing_for_cache`.
    storage_class = settings.BLOCK_STRUCTURES_SETTINGS.get('STORAGE_CLASS')

    # .. setting_name: BLOCK_STRUCTURES_SETTINGS['STORAGE_KWARGS']
    # .. setting_default: {}
    # .. setting_description: Specifies the keyword arguments needed to setup the storage, which
    #   would be used for storage-backed block structure cache.
    #   For more information, check https://github.com/openedx/edx-platform/pull/14571.
    # .. setting_warnings: Depends on `BLOCK_STRUCTURES_SETTINGS['STORAGE_CLASS']` and on
    #   `block_structure.storage_backing_for_cache`.
    storage_kwargs = settings.BLOCK_STRUCTURES_SETTINGS.get('STORAGE_KWARGS', {})

    return get_storage(storage_class, **storage_kwargs)


class CustomizableFileField(models.FileField):
    """
    Subclass of FileField that allows custom settings to not
    be serialized (hard-coded) in migrations. Otherwise,
    migrations include optional settings for storage (such as
    the storage class and bucket name); we don't want to
    create new migration files for each configuration change.
    """
    def __init__(self, *args, **kwargs):
        kwargs.update(dict(
            upload_to=_path_name,
            storage=_bs_model_storage(),
            max_length=500,  # allocate enough for base path + prefix + usage_key + timestamp in filepath
        ))
        super().__init__(*args, **kwargs)

    def deconstruct(self):  # lint-amnesty, pylint: disable=missing-function-docstring
        name, path, args, kwargs = super().deconstruct()
        del kwargs['upload_to']
        del kwargs['storage']
        del kwargs['max_length']
        return name, path, args, kwargs


@contextmanager
def _storage_error_handling(bs_model, operation, is_read_operation=False):
    """
    Helpful context manager that handles various errors
    from the backend storage.

    Typical errors at read time on configuration changes:
        IOError:
            - File not found (S3 or FS)
            - Bucket name changed (S3)
        SuspiciousOperation
            - Path mismatches when changing backends

    Other known errors:
        OSError
            - Access issues in creating files (FS)
        S3ResponseError
            - Incorrect credentials with 403 status (S3)
            - Non-existent bucket with 404 status (S3)
    """
    try:
        yield
    except Exception as error:  # pylint: disable=broad-except
        log.exception('BlockStructure: Exception %s on store %s; %s.', error.__class__, operation, bs_model)
        if isinstance(error, OSError) and error.errno in (errno.EACCES, errno.EPERM):  # lint-amnesty, pylint: disable=no-else-raise, no-member
            raise
        elif is_read_operation and isinstance(error, (IOError, SuspiciousOperation)):
            # May have been caused by one of the possible error
            # situations listed above.  Raise BlockStructureNotFound
            # so the block structure can be regenerated and restored.
            raise BlockStructureNotFound(bs_model.data_usage_key)  # lint-amnesty, pylint: disable=raise-missing-from
        else:
            raise


class BlockStructureModel(TimeStampedModel):
    """
    Model for storing Block Structure information.

    .. no_pii:
    """
    VERSION_FIELDS = [
        'data_version',
        'data_edit_timestamp',
        'transformers_schema_version',
        'block_structure_schema_version',
    ]
    UNIQUENESS_FIELDS = ['data_usage_key'] + VERSION_FIELDS

    class Meta:
        db_table = 'block_structure'

    data_usage_key = UsageKeyWithRunField(
        'Identifier of the data being collected.',
        blank=False,
        max_length=255,
        unique=True,
    )
    data_version = models.CharField(
        'Version of the data at the time of collection.',
        blank=True,
        null=True,
        max_length=255,
    )
    data_edit_timestamp = models.DateTimeField(
        'Edit timestamp of the data at the time of collection.',
        blank=True,
        null=True,
    )
    transformers_schema_version = models.CharField(
        'Representation of the schema version of the transformers used during collection.',
        blank=False,
        max_length=255,
    )
    block_structure_schema_version = models.CharField(
        'Version of the block structure schema at the time of collection.',
        blank=False,
        max_length=255,
    )
    data = CustomizableFileField()

    def get_serialized_data(self):
        """
        Returns the collected data for this instance.
        """
        operation = 'Read'
        with _storage_error_handling(self, operation, is_read_operation=True):
            serialized_data = self.data.read()

        self._log(self, operation, serialized_data)
        return serialized_data

    @classmethod
    def get(cls, data_usage_key):
        """
        Returns the entry associated with the given data_usage_key.
        Raises:
             BlockStructureNotFound if an entry for data_usage_key is not found.
        """
        try:
            return cls.objects.get(data_usage_key=data_usage_key)
        except cls.DoesNotExist:
            log.info('BlockStructure: Not found in table; %s.', data_usage_key)
            raise BlockStructureNotFound(data_usage_key)  # lint-amnesty, pylint: disable=raise-missing-from

    @classmethod
    def update_or_create(cls, serialized_data, data_usage_key, **kwargs):
        """
        Updates or creates the BlockStructureModel entry
        for the given data_usage_key in the kwargs,
        uploading serialized_data as the content data.
        """
        # Use an atomic transaction so the model isn't updated
        # unless the file is successfully persisted.
        with transaction.atomic():
            bs_model, created = cls.objects.update_or_create(defaults=kwargs, data_usage_key=data_usage_key)
            operation = 'Created' if created else 'Updated'

            with _storage_error_handling(bs_model, operation):
                bs_model.data.save('', ContentFile(serialized_data))

        cls._log(bs_model, operation, serialized_data)

        if not created:
            cls._prune_files(data_usage_key)

        return bs_model, created

    def __str__(self):
        """
        Returns a string representation of this model.
        """
        return ', '.join(
            f'{field_name}: {str(getattr(self, field_name))}'
            for field_name in self.UNIQUENESS_FIELDS
        )

    @classmethod
    def _prune_files(cls, data_usage_key, num_to_keep=None):
        """
        Deletes previous file versions for data_usage_key.
        """
        if not settings.BLOCK_STRUCTURES_SETTINGS.get('PRUNING_ACTIVE', False):
            return

        if num_to_keep is None:
            num_to_keep = config.num_versions_to_keep()

        try:
            all_files_by_date = sorted(cls._get_all_files(data_usage_key))
            files_to_delete = all_files_by_date[:-num_to_keep] if num_to_keep > 0 else all_files_by_date  # lint-amnesty, pylint: disable=invalid-unary-operand-type
            cls._delete_files(files_to_delete)
            log.info(
                'BlockStructure: Deleted %d out of total %d files in store; data_usage_key: %s, num_to_keep: %d.',
                len(files_to_delete),
                len(all_files_by_date),
                data_usage_key,
                num_to_keep,
            )

        except Exception:  # pylint: disable=broad-except
            log.exception('BlockStructure: Exception when deleting old files; data_usage_key: %s.', data_usage_key)

    @classmethod
    def _delete_files(cls, files):
        """
        Deletes the given files from storage.
        """
        storage = _bs_model_storage()
        list(map(storage.delete, files))

    @classmethod
    def _get_all_files(cls, data_usage_key):
        """
        Returns all filenames that exist for the given key.
        """
        directory = _directory_name(data_usage_key)
        _, filenames = _bs_model_storage().listdir(directory)
        return [
            _create_path(directory, filename)
            for filename in filenames
            if filename and not filename.startswith('.')
        ]

    @classmethod
    def _log(cls, bs_model, operation, serialized_data):
        """
        Writes log information for the given values.
        """
        log.info(
            'BlockStructure: %s in store %s at %s%s; %s, size: %d',
            operation,
            bs_model.data.storage.__class__,
            getattr(bs_model.data.storage, 'bucket_name', ''),
            getattr(bs_model.data.storage, 'location', ''),
            bs_model,
            len(serialized_data),
        )


class ApiCourseStructure(models.Model):
    block_id = models.CharField(max_length=255, null=False, blank=False, db_index=True, unique=True)
    block_type = models.CharField(max_length=255, null=False, blank=False)
    parent_id = models.CharField(max_length=255, null=True)
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    display_name = models.TextField(null=True, blank=True)
    graded = models.SmallIntegerField(null=False)
    section_path = models.TextField(null=True, blank=True)
    deleted = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_course_structure'

    def to_dict(self):
        return {
            'block_id': self.block_id,
            'block_type': self.block_type,
            'parent_id': self.parent_id,
            'course_id': self.course_id,
            'display_name': self.display_name,
            'graded': bool(self.graded)
        }


class ApiCourseStructureTags(models.Model):
    org_id = models.CharField(max_length=80, null=True, db_index=True)
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    block = models.ForeignKey(ApiCourseStructure, on_delete=models.CASCADE, to_field='block_id')
    block_tag_id = models.CharField(max_length=80, null=True)
    rubric = models.CharField(max_length=255, null=True, blank=False,
                              help_text="Should be filled in only for ORA blocks")
    tag_name = models.CharField(max_length=255, null=False, blank=False)
    tag_value = models.CharField(max_length=255, null=False, blank=False, db_index=True)
    root_tag_value_hash = models.CharField(max_length=80, null=True, blank=False)
    is_parent = models.SmallIntegerField(default=0)
    ts = models.IntegerField(null=True, db_index=True)

    class Meta:
        managed = False
        db_table = 'api_course_structure_tags'


class ApiCourseStructureUpdateTime(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    processed = models.BooleanField(default=False)

    class Meta:
        db_table = 'api_course_structure_update_time'


class ApiCourseStructureLockResult:

    def __init__(self, is_locked=False, is_new=False, lock=None):
        self.is_locked = is_locked
        self.is_new = is_new
        self.lock = lock


class ApiCourseStructureLock(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    created = models.DateTimeField()
    task_id = models.CharField(max_length=255, null=True)
    published_on = models.CharField(max_length=255, null=True)

    class Meta:
        db_table = 'api_course_structure_lock'


class ApiBlockInfo(models.Model):
    course_id = models.CharField(max_length=255, null=False, db_index=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    hash_id = models.CharField(max_length=255, null=False, db_index=True)
    deleted = models.BooleanField(default=False)
    has_children = models.BooleanField(default=False)
    created_by = models.IntegerField(null=True, default=None)
    created_time = models.DateTimeField(null=True, default=None)
    updated_by = models.IntegerField(null=True, default=None)
    updated_time = models.DateTimeField(null=True, default=None)
    created_as_copy = models.BooleanField(default=False)
    created_as_copy_from_course_id = models.CharField(max_length=255, null=True, blank=True)
    published_after_copy = models.BooleanField(default=False)
    published_content_version = models.CharField(max_length=255, null=True, blank=False, db_index=True)
    reverted_to_previous_version = models.BooleanField(default=False)

    CATEGORY_HAS_CHILDREN = ('chapter', 'sequential', 'vertical')

    def set_has_children(self):
        if self.block_id:
            category = self.block_id.split('@')[1].split('+')[0]
            if category in self.CATEGORY_HAS_CHILDREN:
                self.has_children = True
            else:
                self.has_children = False
        else:
            self.has_children = False

    class Meta:
        db_table = 'api_block_info'
        unique_together = (('course_id', 'block_id'),)


class ApiBlockInfoNotSiblings(models.Model):
    source_block_id = models.CharField(max_length=255, null=False, db_index=True)
    dst_block_id = models.CharField(max_length=255, null=False, db_index=True)
    source_course_id = models.CharField(max_length=255, null=True, db_index=True)
    dst_course_id = models.CharField(max_length=255, null=True, db_index=True)

    user_id = models.IntegerField(null=True, default=None)
    created = models.DateTimeField(null=True, blank=True, auto_now_add=True)
    updated = models.DateTimeField(null=True, blank=True, auto_now=True)

    class Meta:
        db_table = 'api_block_info_not_siblings'
        verbose_name = "Cousin Content Block"
        verbose_name_plural = "Cousin Content Blocks"


class ApiBlockInfoVersionsHistory(models.Model):
    course_id = models.CharField(max_length=255, null=False, db_index=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    version_id = models.CharField(max_length=255)
    siblings_hash_id = models.CharField(max_length=255, null=False)

    class Meta:
        db_table = 'api_block_info_versions_history'


class BlockCache(models.Model):
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    block_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    field_name = models.CharField(max_length=255, null=False, blank=False)
    field_value = models.CharField(max_length=255, null=False, blank=False)

    class Meta:
        db_table = 'api_block_cache'
        index_together = (('field_name', 'field_value'),)
        unique_together = (('block_id', 'field_name'),)

    @classmethod
    def update_cache(cls, course_id, block_id, field_name, field_value=None):
        if field_value == '':
            field_value = None

        obj = BlockCache.objects.filter(block_id=block_id, field_name=field_name).first()
        if obj and field_value is None:
            obj.delete()
        elif obj and field_value != obj.field_value:
            obj.field_value = field_value
            obj.save()
        elif not obj and field_value is not None:
            obj = BlockCache(
                course_id=course_id,
                block_id=block_id,
                field_name=field_name,
                field_value=field_value
            )
            obj.save()
        return obj


class BlockToSequential(models.Model):
    block_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    sequential_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    sequential_name = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    course_id = models.CharField(max_length=255, db_index=True, null=False, blank=False)
    graded = models.SmallIntegerField(null=False)
    deleted = models.BooleanField(default=False)
    visible_to_staff_only = models.BooleanField(default=False)

    class Meta:
        db_table = 'block_to_sequential'


class CourseAuthProfileFieldsCache(models.Model):
    course_id = models.CharField(max_length=255, unique=True)
    data = models.TextField(null=True, blank=True)

    class Meta:
        db_table = 'course_auth_profile_fields_cache'

    def get_fields(self):
        if self.data:
            return json.loads(self.data)
        return None


class CourseFieldsCache(models.Model):
    course_id = models.CharField(max_length=255, unique=True)
    additional_profile_fields = models.TextField(null=True, blank=True)
    enable_subsection_gating = models.BooleanField(null=True)

    @classmethod
    def get_cache(cls, course_id, course=None, force_refresh=False, check_attr_to_refresh=None):
        course_key = CourseKey.from_string(course_id)
        obj_exists = True
        try:
            obj = cls.objects.get(course_id=course_id)
        except cls.DoesNotExist:
            obj = CourseFieldsCache(course_id=course_id)
            obj_exists = False

        if not obj_exists or force_refresh or\
          (check_attr_to_refresh and (getattr(obj, check_attr_to_refresh, None) is None)):
            additional_profile_fields_keys = set()
            additional_profile_fields = {}
            enable_subsection_gating = False
            need_update = False

            if course:
                if course.credo_additional_profile_fields:
                    additional_profile_fields = json.dumps(course.credo_additional_profile_fields)
                    additional_profile_fields_keys = set(course.credo_additional_profile_fields.keys())
                enable_subsection_gating = course.enable_subsection_gating
            else:
                fields_data = {}
                course_structure = get_course_structure(course_key)
                if course_structure:
                    for st in course_structure['blocks']:
                        if st['block_type'] == 'course':
                            fields_data = st.get('fields', {})
                            break
                if fields_data:
                    if 'credo_additional_profile_fields' in fields_data and fields_data['credo_additional_profile_fields']:
                        additional_profile_fields = json.dumps(fields_data['credo_additional_profile_fields'])
                        additional_profile_fields_keys = set(fields_data['credo_additional_profile_fields'].keys())
                    if 'enable_subsection_gating' in fields_data:
                        enable_subsection_gating = fields_data['enable_subsection_gating']

            additional_profile_fields_keys_current = None
            additional_profile_fields_current = obj.get_additional_profile_fields()
            if additional_profile_fields_current:
                additional_profile_fields_keys_current = set(additional_profile_fields_current.keys())

            if additional_profile_fields_keys != additional_profile_fields_keys_current:
                obj.additional_profile_fields = additional_profile_fields
                need_update = True

            if enable_subsection_gating != obj.enable_subsection_gating:
                obj.enable_subsection_gating = enable_subsection_gating
                need_update = True

            if need_update:
                obj.save()

        return obj

    @classmethod
    def refresh_cache(cls, course_id, course=None):
        cls.get_cache(course_id, course=course, force_refresh=True)

    class Meta:
        db_table = 'course_fields_cache'

    def get_additional_profile_fields(self):
        if self.additional_profile_fields:
            return json.loads(self.additional_profile_fields)
        return None


class OraBlockStructure(models.Model):
    course_id = models.CharField(max_length=255, null=False, db_index=True)
    org_id = models.CharField(max_length=80, null=False, db_index=True)
    block_id = models.CharField(max_length=255, null=False, db_index=True)
    is_ora_empty_rubrics = models.BooleanField(default=False)
    support_multiple_rubrics = models.BooleanField(default=False)
    is_additional_rubric = models.BooleanField(default=False)
    prompt = models.TextField(null=True)
    rubric_criteria = models.TextField(null=True)
    display_rubric_step_to_students = models.BooleanField(default=False)
    steps = models.TextField(null=True)
    ungraded = models.BooleanField(default=False)

    class Meta:
        db_table = 'ora_block_structure'

    def get_rubric_criteria(self):
        return json.loads(self.rubric_criteria)

    def get_steps(self):
        return json.loads(self.steps)
