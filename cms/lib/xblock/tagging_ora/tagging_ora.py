# -*- coding: utf-8 -*-
"""
Structured Tagging based on XBlockAsides
"""

import json
from ..tagging import StructuredTagsAside
from xblock.core import XBlockAside, XBlock
from xblock.fragment import Fragment
from xmodule.x_module import AUTHOR_VIEW
from edxmako.shortcuts import render_to_string
from django.core.exceptions import ObjectDoesNotExist
from webob import Response
from student.models import User


_ = lambda text: text


class OraStructuredTagsAside(StructuredTagsAside):
    """
    Aside that allows tagging blocks
    """

    @XBlockAside.aside_for(AUTHOR_VIEW)
    def student_view_aside(self, block, context):  # pylint: disable=unused-argument
        """
        Display the tag selector with specific categories and allowed values,
        depending on the context.
        """
        if block.category == 'openassessment':
            tags = []
            user = None
            has_access_any_tag = False

            rubrics = [rubric['label'].strip() for rubric in block.rubric_criteria]

            for tag in self.get_available_tags():
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
                    current_values = self.saved_tags.get(rubric, {}).get(tag.name, [])

                    if isinstance(current_values, basestring):
                        current_values = [current_values]

                    values_not_exists = [cur_val for cur_val in current_values if cur_val not in values]
                    rubrics_current_values[rubric] = {
                        'current_values': values_not_exists + current_values,
                        'current_values_json': json.dumps(values_not_exists + current_values)
                    }

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
            fragment.add_css_url(self._get_studio_resource_url('/cms/css/magicsuggest-1.3.1.css'))
            fragment.add_javascript_url(self._get_studio_resource_url('/cms/js/magicsuggest-1.3.1.js'))
            fragment.add_javascript_url(self._get_studio_resource_url('/js/xblock_asides/ora_structured_tags.js'))
            fragment.initialize_js('OraStructuredTagsInit')
            return fragment
        else:
            return Fragment(u'')

    @XBlock.handler
    def save_tags(self, request=None, suffix=None):  # pylint: disable=unused-argument
        """
        Handler to save chosen tags with connected XBlock
        """
        try:
            posted_data = request.json
        except ValueError:
            return Response("Invalid request body", status=400)

        saved_tags = {}
        need_update = False

        for av_tag in self.get_available_tags():
            for rubric, rubric_tags in posted_data.iteritems():
                if av_tag.name in rubric_tags and rubric_tags[av_tag.name]:
                    tag_available_values = av_tag.get_values()
                    tag_current_values = self.saved_tags.get(rubric, {}).get(av_tag.name, [])

                    if isinstance(tag_current_values, basestring):
                        tag_current_values = [tag_current_values]

                    for posted_tag_value in rubric_tags[av_tag.name]:
                        if posted_tag_value not in tag_available_values and posted_tag_value not in tag_current_values:
                            return Response("Invalid tag value was passed: %s" % posted_tag_value, status=400)

                    if rubric not in saved_tags:
                        saved_tags[rubric] = {}
                    saved_tags[rubric][av_tag.name] = rubric_tags[av_tag.name]
                    need_update = True
                if av_tag.name in rubric:
                    need_update = True

        if need_update:
            self.saved_tags = saved_tags
            return Response()
        else:
            return Response("Tags parameters were not passed", status=400)

    def get_event_context(self, event_type, event):  # pylint: disable=unused-argument
        """
        This method return data that should be associated with the "check_problem" event
        """
        if self.saved_tags:
            if event_type.startswith('openassessmentblock.') or event_type.startswith('openassessment.'):
                return {'saved_tags': self.saved_tags}
        return None
