# -*- coding: utf-8 -*-
"""
Structured Tagging based on XBlockAsides
"""

import json
from xblock.core import XBlockAside, XBlock
from web_fragments.fragment import Fragment
from xblock.fields import Scope, Dict
from xmodule.x_module import AUTHOR_VIEW
from xmodule.capa_module import CapaModule
from edxmako.shortcuts import render_to_string
from django.conf import settings
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist
from webob import Response


_ = lambda text: text


class StructuredTagsAside(XBlockAside):
    """
    Aside that allows tagging blocks
    """
    saved_tags = Dict(help=_("Dictionary with the available tags"),
                      scope=Scope.content,
                      default={},)

    def get_available_tags(self):
        """
        Return available tags
        """
        from .models import TagCategories
        return TagCategories.objects.all()

    def _get_studio_resource_url(self, relative_url):
        """
        Returns the Studio URL to a static resource.
        """
        return settings.STATIC_URL + relative_url

    def _check_user_access(self, role, user=None):
        from student.auth import user_has_role
        from student.roles import CourseStaffRole, CourseInstructorRole
        roles = {
            CourseStaffRole.ROLE: CourseStaffRole,
            CourseInstructorRole.ROLE: CourseInstructorRole
        }

        if not user:
            return False
        elif self.runtime.user_is_superuser:
            return True
        elif role in roles:
            return user_has_role(user, roles[role](self.runtime.course_id))

        return False

    @XBlockAside.aside_for(AUTHOR_VIEW)
    def student_view_aside(self, block, context):  # pylint: disable=unused-argument
        """
        Display the tag selector with specific categories and allowed values,
        depending on the context.
        """
        from student.models import User

        if isinstance(block, CapaModule) or block.category in ['html', 'video', 'drag-and-drop-v2'] or \
                (block.category == 'openassessment' and len(block.rubric_criteria) == 0):
            tags = []
            user = None
            has_access_any_tag = False

            for tag in self.get_available_tags():
                course_id = None
                org = None

                if tag.scoped_by:
                    if tag.scoped_by == 'course':
                        course_id = self.scope_ids.usage_id.course_key
                    elif tag.scoped_by == 'org':
                        org = self.scope_ids.usage_id.course_key.org

                values = tag.get_values(course_id=course_id, org=org)
                current_values = self.saved_tags.get(tag.name, [])

                if isinstance(current_values, basestring):
                    current_values = [current_values]

                values_not_exists = [cur_val for cur_val in current_values if cur_val not in values]
                has_access_this_tag = True

                if tag.role:
                    if not user:
                        try:
                            user = User.objects.get(pk=self.runtime.user_id)
                        except ObjectDoesNotExist:
                            pass
                    has_access_this_tag = self._check_user_access(tag.role, user)
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
            fragment = Fragment(render_to_string('structured_tags_block.html', {'tags': tags,
                                                                                'tags_count': len(tags),
                                                                                'block_location': block.location,
                                                                                'show_save_btn': has_access_any_tag,
                                                                                }))
            fragment.add_javascript_url(self._get_studio_resource_url('/cms/js/magicsuggest-1.3.1.js'))
            fragment.add_javascript_url(self._get_studio_resource_url('/js/xblock_asides/structured_tags.js'))
            fragment.initialize_js('StructuredTagsInit')
            return fragment
        else:
            return Fragment(u'')

    @XBlock.handler
    def edit_tags_view(self, request=None, suffix=None):  # pylint: disable=unused-argument
        from .models import TagCategories
        tag_category_param = request.GET.get('tag_category', None)

        if tag_category_param:
            try:
                tag = TagCategories.objects.get(name=tag_category_param)

                course_id = None
                org = None

                if tag.scoped_by:
                    if tag.scoped_by == 'course':
                        course_id = self.scope_ids.usage_id.course_key
                    elif tag.scoped_by == 'org':
                        org = self.scope_ids.usage_id.course_key.org

                tpl_params = {
                    'key': tag.name,
                    'title': tag.title,
                    'values': '\n'.join(tag.get_values(course_id=course_id, org=org))
                }

                data = {
                    'html': render_to_string('structured_tags_block_editor.html', tpl_params)
                }
                return Response(json=data)
            except TagCategories.DoesNotExist:
                pass

        return Response("Invalid 'tag_category' parameter", status=400)

    @XBlock.handler
    def update_values(self, request=None, suffix=None):  # pylint: disable=unused-argument
        with transaction.atomic():
            for tag_key in request.POST:
                for tag in self.get_available_tags():
                    if tag.name == tag_key:
                        course_id = None
                        org = None

                        if tag.scoped_by:
                            if tag.scoped_by == 'course':
                                course_id = self.scope_ids.usage_id.course_key
                            elif tag.scoped_by == 'org':
                                org = self.scope_ids.usage_id.course_key.org

                        tag_values = tag.get_values(course_id=course_id, org=org)
                        tmp_list = [v for v in request.POST[tag_key].splitlines() if v.strip()]

                        values_to_add = list(set(tmp_list) - set(tag_values))
                        values_to_remove = list(set(tag_values) - set(tmp_list))

                        self._add_tag_values(tag, values_to_add, course_id, org)
                        self._remove_tag_values(tag, values_to_remove, course_id, org)
        return Response()

    def _add_tag_values(self, tag_category, values, course_id=None, org=None):
        from .models import TagAvailableValues
        for val in values:
            kwargs = {
                'category': tag_category,
                'value': val
            }
            if course_id:
                kwargs['course_id'] = course_id
            if org:
                kwargs['org'] = org
            TagAvailableValues(**kwargs).save()

    def _remove_tag_values(self, tag_category, values, course_id=None, org=None):
        from .models import TagAvailableValues
        for val in values:
            kwargs = {
                'category': tag_category,
                'value': val
            }
            if course_id:
                kwargs['course_id'] = course_id
            if org:
                kwargs['org'] = org
            TagAvailableValues.objects.filter(**kwargs).delete()

    @XBlock.handler
    def save_tags(self, request=None, suffix=None):  # pylint: disable=unused-argument
        """
        Handler to save chosen tags with connected XBlock
        """
        posted_data = request.params.dict_of_lists()
        saved_tags = {}

        for av_tag in self.get_available_tags():
            tag_key = '%s[]' % av_tag.name
            if tag_key in posted_data and len(posted_data[tag_key]) > 0:
                saved_tags[av_tag.name] = posted_data[tag_key]

        self.saved_tags = saved_tags
        return Response()

    def get_event_context(self, event_type, event):  # pylint: disable=unused-argument
        """
        This method return data that should be associated with the "check_problem" event
        """
        if self.saved_tags and event_type in ("problem_check", "edx.drag_and_drop_v2.item.dropped"):
            return {'saved_tags': self.saved_tags}
        else:
            return None
