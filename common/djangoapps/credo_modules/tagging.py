import json
from django.db.models import Q
from django.core.exceptions import ObjectDoesNotExist
from credo_modules.models import Organization
from student.models import User


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
    from student.auth import user_has_role
    from student.roles import CourseStaffRole, CourseInstructorRole
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


def get_tags(course_key, org_val, user_id, saved_tags=None, user_is_superuser=False):
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

        tags.append({
            'key': tag.name,
            'title': tag.title,
            'values': values,
            'values_json': json.dumps(values),
            'current_values': values_not_exists + current_values,
            'current_values_json': json.dumps(values_not_exists + current_values),
            'editable': tag.editable_in_studio,
            'has_access': has_access_this_tag,
        })

    return tags, has_access_any_tag
