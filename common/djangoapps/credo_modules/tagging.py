import hashlib
import json
from django.db.models import Q
from django.core.exceptions import ObjectDoesNotExist
from common.djangoapps.credo_modules.models import Organization
from django.contrib.auth import get_user_model


User = get_user_model()


def get_available_tags(org):
    """
    Return available tags
    """
    from cms.lib.xblock.tagging.models import TagCategories

    org_type_id = None
    try:
        cr_org = Organization.objects.get(org=org)
        if cr_org.org_type is not None:
            org_type_id = cr_org.org_type.id
    except Organization.DoesNotExist:
        pass

    if org_type_id:
        return TagCategories.objects.filter(Q(org_types__org_type=None) | Q(org_types__org_type=org_type_id))
    return TagCategories.objects.filter(org_types__org_type=None)


def check_user_access(role, course_id, user=None, user_is_superuser=False):
    from common.djangoapps.student.auth import user_has_role
    from common.djangoapps.student.roles import CourseStaffRole, CourseInstructorRole
    roles = {
        CourseStaffRole.ROLE: CourseStaffRole,
        CourseInstructorRole.ROLE: CourseInstructorRole
    }

    if not user:
        return False
    elif user_is_superuser:
        return True
    elif role in roles:
        return user_has_role(user, roles[role](course_id))

    return False


def get_tags(course_key, org_val, user_id, saved_tags=None, tags_history=None, user_is_superuser=False):
    tags = []
    user = None
    has_access_any_tag = False

    for tag in get_available_tags(org_val):
        course_id = None
        org = None

        if tag.scoped_by:
            if tag.scoped_by == 'course':
                course_id = course_key
            elif tag.scoped_by == 'org':
                org = org_val

        values = tag.get_values(course_id=course_id, org=org)
        current_values = saved_tags.get(tag.name, []) if saved_tags is not None else []

        if isinstance(current_values, str):
            current_values = [current_values]
        current_values = [v.replace('–', '-').strip().encode("utf-8").decode('ascii', errors='ignore')
                          for v in current_values]

        values_not_exists = [cur_val for cur_val in current_values if cur_val not in values]
        has_access_this_tag = True

        if tag.role:
            if not user:
                try:
                    user = User.objects.get(pk=user_id)
                except ObjectDoesNotExist:
                    pass
            has_access_this_tag = check_user_access(tag.role, course_key, user, user_is_superuser)
            if has_access_this_tag:
                has_access_any_tag = True
        else:
            has_access_any_tag = True

        prepared_values = prepare_tag_values(
            tag.name, values, current_values, tags_history=tags_history,
            disable_superusers_tags=tag.disable_superusers_tags, user_is_superuser=user_is_superuser
        )

        tags.append({
            'key': tag.name,
            'title': tag.title,
            'values': values,
            'values_json': json.dumps(prepared_values),
            'values_json_lst': json.dumps(values),
            'current_values': values_not_exists + current_values,
            'current_values_json': json.dumps(values_not_exists + current_values),
            'editable': tag.editable_in_studio,
            'has_access': has_access_this_tag,
        })

    return tags, has_access_any_tag


def prepare_tag_values(tag_category, values, current_values, tags_history=False,
                       disable_superusers_tags=False, user_is_superuser=False, rubric=None):
    if not tags_history:
        tags_history = {}
    ret = []
    disabled_tags = []
    for v in values:
        disabled = False
        if disable_superusers_tags and not user_is_superuser and v in current_values:
            tag_key = get_tag_key(tag_category, v, rubric=rubric)
            tag_history = tags_history.get(tag_key)
            if not tag_history or tag_history[0] is True:
                disabled = True
                disabled_tags.append(v)

        ret.append({
            'name': v,
            'disabled': disabled
        })
    return sorted(ret, key=lambda k: ('0-' if k['disabled'] else '1-') + k['name'])


def get_tag_key(tag_category, tag_value, rubric=None):
    if rubric is None:
        tag_token = tag_category + '|' + tag_value
    else:
        tag_token = rubric + '|' + tag_category + '|' + tag_value
    return hashlib.md5(tag_token.encode('utf-8')).hexdigest()
