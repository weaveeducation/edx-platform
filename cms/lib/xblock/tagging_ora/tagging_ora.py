# -*- coding: utf-8 -*-
"""
Structured Tagging based on XBlockAsides
"""

import json
from ..tagging import StructuredTagsAside
from xblock.core import XBlockAside, XBlock
from web_fragments.fragment import Fragment
from xmodule.x_module import AUTHOR_VIEW
from common.djangoapps.edxmako.shortcuts import render_to_string
from common.djangoapps.xblock_django.constants import ATTR_KEY_USER_ID, ATTR_KEY_USER_IS_SUPERUSER
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth import get_user_model
from webob import Response


_ = lambda text: text


@XBlock.needs('user')
class OraStructuredTagsAside(StructuredTagsAside):
    """
    Aside that allows tagging blocks
    """

    def prepare_rubric_name(self, rubric):
        return rubric.replace('.', '_dot_').strip()

    @XBlockAside.aside_for(AUTHOR_VIEW)
    def student_view_aside(self, block, context):  # pylint: disable=unused-argument
        """
        Display the tag selector with specific categories and allowed values,
        depending on the context.
        """
        from common.djangoapps.credo_modules.tagging import prepare_tag_values
        User = get_user_model()

        if block.category == 'openassessment':
            if len(block.rubric_criteria) == 0:
                return super().student_view_aside(block, context)
            tags = []
            user = None
            has_access_any_tag = False

            user_service = self.runtime.service(self, 'user')
            user_id = user_service.get_current_user().opt_attrs.get(ATTR_KEY_USER_ID)
            user_is_superuser = user_service.get_current_user().opt_attrs.get(ATTR_KEY_USER_IS_SUPERUSER)

            rubrics = [rubric['label'].strip() for rubric in block.rubric_criteria]

            for tag in self._get_available_tags():
                course_id = None
                org = None

                if tag.scoped_by:
                    if tag.scoped_by == 'course':
                        course_id = self.scope_ids.usage_id.course_key
                    elif tag.scoped_by == 'org':
                        org = self.scope_ids.usage_id.course_key.org

                values = tag.get_values(course_id=course_id, org=org)

                rubrics_current_values = {}

                for rubric in rubrics:
                    current_values = self.saved_tags.get(self.prepare_rubric_name(rubric), {}).get(tag.name, [])

                    if isinstance(current_values, str):
                        current_values = [current_values]

                    values_not_exists = [cur_val for cur_val in current_values if cur_val not in values]
                    prepared_values = prepare_tag_values(
                        tag.name, values, current_values, tags_history=self.tags_history,
                        disable_superusers_tags=tag.disable_superusers_tags, user_is_superuser=user_is_superuser,
                        rubric=rubric)
                    rubrics_current_values[rubric] = {
                        'values_json': json.dumps(prepared_values),
                        'current_values': values_not_exists + current_values,
                        'current_values_json': json.dumps(values_not_exists + current_values)
                    }

                has_access_this_tag = True

                if tag.role:
                    if not user:
                        try:
                            user = User.objects.get(pk=user_id)
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
                    'rubrics_current_values': rubrics_current_values,
                    'editable': tag.editable_in_studio,
                    'has_access': has_access_this_tag,
                })
            fragment = Fragment(render_to_string('ora_structured_tags_block.html', {'rubrics': rubrics,
                                                                                    'tags': tags,
                                                                                    'tags_count': len(tags),
                                                                                    'block_location': block.location,
                                                                                    'show_save_btn': has_access_any_tag,
                                                                                    }))
            fragment.add_javascript_url(self._get_studio_resource_url('/cms/js/magicsuggest-1.3.1.js'))
            fragment.add_javascript_url(self._get_studio_resource_url('/js/xblock_asides/ora_structured_tags.js'))
            fragment.initialize_js('OraStructuredTagsInit')
            return fragment
        else:
            return Fragment('')

    @XBlock.handler
    def save_ora_tags(self, request=None, suffix=None):  # pylint: disable=unused-argument
        """
        Handler to save chosen tags with connected XBlock
        """
        from common.djangoapps.credo_modules.tagging import get_tag_key
        try:
            posted_data = request.json
        except ValueError:
            return Response("Invalid request body", status=400)

        user_service = self.xmodule_runtime.service(self, 'user')

        user_id = user_service.get_user_id()
        user_is_superuser = user_service.is_superadmin_user()

        saved_tags = {}
        tags_history = {}

        for av_tag in self._get_available_tags():
            for rubric, rubric_tags in posted_data.items():
                tag_category = av_tag.name.strip()
                rubric_name = self.prepare_rubric_name(rubric)
                saved_tag_values = self.saved_tags.get(rubric_name, {}).get(tag_category, [])

                if tag_category in rubric_tags and rubric_tags[tag_category]:
                    tag_available_values = av_tag.get_values()

                    if isinstance(saved_tag_values, str):
                        saved_tag_values = [saved_tag_values]

                    for posted_tag_value in rubric_tags[tag_category]:
                        tag_value_final = posted_tag_value.strip()
                        tag_key = get_tag_key(av_tag.name, tag_value_final, rubric)

                        if tag_value_final not in tag_available_values and tag_value_final not in saved_tag_values:
                            return Response("Invalid tag value was passed: %s" % tag_value_final, status=400)

                        if tag_key not in self.tags_history:
                            added_by_superuser = False
                            added_by_user = 0
                            if tag_value_final in saved_tag_values or user_is_superuser:
                                added_by_superuser = True
                            if tag_value_final not in saved_tag_values:
                                added_by_user = user_id
                            tags_history[tag_key] = [added_by_superuser, added_by_user]
                        else:
                            tags_history[tag_key] = self.tags_history[tag_key].copy()

                    if rubric_name not in saved_tags:
                        saved_tags[rubric_name] = {}
                    saved_tags[rubric_name][tag_category] = rubric_tags[tag_category]

        self.saved_tags = saved_tags
        self.tags_history = tags_history
        return Response()

    def get_event_context(self, event_type, event):  # pylint: disable=unused-argument
        """
        This method return data that should be associated with the "check_problem" event
        """
        if self.saved_tags:
            if event_type.startswith('openassessmentblock.') or event_type.startswith('openassessment.'):
                return {'saved_tags': self.saved_tags}
        return None

    def get_sorted_tags(self):
        res = {}
        for rubric, saved_tags in self.saved_tags.items():
            r_name = rubric.strip()
            if isinstance(saved_tags, dict):
                for tag_name, tag_values in saved_tags.items():
                    if isinstance(tag_values, list):
                        res[r_name + '|' + tag_name.strip()] = sorted(tag_values)
        return res
