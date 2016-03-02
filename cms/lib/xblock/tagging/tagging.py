# -*- coding: utf-8 -*-
"""
Structured Tagging based on XBlockAsides
"""

from xblock.core import XBlockAside, XBlock
from xblock.fragment import Fragment
from xblock.fields import Scope, Dict
from xmodule.x_module import STUDENT_VIEW
from xmodule.capa_module import CapaModule
from abc import ABCMeta, abstractproperty
from edxmako.shortcuts import render_to_string
from django.conf import settings
from django.db import transaction
from webob import Response
from .models import AvailableTags


_ = lambda text: text


class AbstractTag(object):
    """
    Abstract class for tags
    """
    __metaclass__ = ABCMeta

    @abstractproperty
    def key(self):
        """
        Subclasses must implement key
        """
        raise NotImplementedError('Subclasses must implement key')

    @abstractproperty
    def name(self):
        """
        Subclasses must implement name
        """
        raise NotImplementedError('Subclasses must implement name')

    def get_values(self, course_id):
        """ Allowed values for the selector """
        tags = [v.tag for v in AvailableTags.objects.filter(course_id=course_id, category=self.key)]
        return tags[:]


class DifficultyTag(AbstractTag):
    """
    Particular implementation tags for difficulty
    """
    @property
    def key(self):
        """ Identifier for the difficulty selector """
        return 'difficulty_tag'

    @property
    def name(self):
        """ Label for the difficulty selector """
        return _('Difficulty')


class LearningOutcomeTag(AbstractTag):
    """
    Particular implementation tags for learning outcomes
    """
    @property
    def key(self):
        """ Identifier for the learning outcome selector """
        return 'learning_outcome_tag'

    @property
    def name(self):
        """ Label for the learning outcome selector """
        return _('Learning outcomes')


class StructuredTagsAside(XBlockAside):
    """
    Aside that allows tagging blocks
    """
    saved_tags = Dict(help=_("Dictionary with the available tags"),
                      scope=Scope.content,
                      default={},)
    available_tags = [DifficultyTag(), LearningOutcomeTag()]

    def _get_studio_resource_url(self, relative_url):
        """
        Returns the Studio URL to a static resource.
        """
        return settings.STATIC_URL + relative_url

    @XBlockAside.aside_for(STUDENT_VIEW)
    def student_view_aside(self, block, context):  # pylint: disable=unused-argument
        """
        Display the tag selector with specific categories and allowed values,
        depending on the context.
        """
        course_key = self.scope_ids.usage_id.course_key
        if isinstance(block, CapaModule):
            tags = []
            for tag in self.available_tags:
                values = tag.get_values(course_key)
                current_value = self.saved_tags.get(tag.key, None)

                if current_value is not None and current_value not in values:
                    values.insert(0, current_value)

                tags.append({
                    'key': tag.key,
                    'title': tag.name,
                    'values': values,
                    'current_value': current_value
                })
            fragment = Fragment(render_to_string('structured_tags_block.html', {'tags': tags}))
            fragment.add_javascript_url(self._get_studio_resource_url('/js/xblock_asides/structured_tags.js'))
            fragment.initialize_js('StructuredTagsInit')
            return fragment
        else:
            return Fragment(u'')

    @XBlock.handler
    def save_tags(self, request=None, suffix=None):  # pylint: disable=unused-argument
        """
        Handler to save choosen tags with connected XBlock
        """
        found = False
        if 'tag' not in request.params:
            return Response("The required parameter 'tag' is not passed", status=400)

        tag = request.params['tag'].split(':')

        course_key = self.scope_ids.usage_id.course_key
        for av_tag in self.available_tags:
            if av_tag.key == tag[0]:
                if tag[1] in av_tag.get_values(course_key):
                    self.saved_tags[tag[0]] = tag[1]
                    found = True
                elif tag[1] == '':
                    self.saved_tags[tag[0]] = None
                    found = True

        if not found:
            return Response("Invalid 'tag' parameter", status=400)

        return Response()

    @XBlock.handler
    def edit_tags_view(self, request=None, suffix=None):  # pylint: disable=unused-argument
        course_key = self.scope_ids.usage_id.course_key

        tags = []
        for tag in self.available_tags:
            tags.append({
                'key': tag.key,
                'title': tag.name,
                'values': '\n'.join(tag.get_values(course_key))
            })

        data = {
            'html': render_to_string('structured_tags_block_editor.html', {'tags': tags})
        }
        return Response(json=data)

    @XBlock.handler
    def update_values(self, request=None, suffix=None):  # pylint: disable=unused-argument
        course_key = self.scope_ids.usage_id.course_key

        tags_dict = {}
        for available_tag in self.available_tags:
            tags_dict[available_tag.key] = available_tag

        with transaction.atomic():
            for tag_key in request.POST:
                tag = tags_dict.get(tag_key, None)
                if tag:
                    new_tag_values = []
                    tmp_list = [v for v in request.POST[tag_key].splitlines() if v.strip()]
                    for tmp in tmp_list:
                        val = tmp.strip()
                        if val not in new_tag_values:
                            new_tag_values.append(val)
                    if new_tag_values:
                        self._update_tag(course_key, tag, new_tag_values)

        return Response()

    def _update_tag(self, course_id, tag, data):
        AvailableTags.objects.filter(course_id=course_id, category=tag.key).delete()
        for value in data:
            AvailableTags(course_id=course_id, category=tag.key, tag=value).save()

