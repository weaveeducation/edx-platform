"""
Views to show a course outline.
"""


import datetime
import re
import six  # lint-amnesty, pylint: disable=unused-import
import logging

from completion.waffle import ENABLE_COMPLETION_TRACKING_SWITCH
from django.contrib.auth.models import User  # lint-amnesty, pylint: disable=imported-auth-user
from django.db.models import Q  # lint-amnesty, pylint: disable=unused-import
from django.shortcuts import redirect  # lint-amnesty, pylint: disable=unused-import
from django.template.context_processors import csrf
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone  # lint-amnesty, pylint: disable=unused-import
from django.views.decorators.csrf import ensure_csrf_cookie  # lint-amnesty, pylint: disable=unused-import
import edx_when.api as edx_when_api
from opaque_keys.edx.keys import CourseKey
from pytz import UTC
from waffle.models import Switch
from web_fragments.fragment import Fragment

from lms.djangoapps.courseware.access import has_access  # lint-amnesty, pylint: disable=unused-import
from lms.djangoapps.courseware.courses import get_course_overview_with_access
from lms.djangoapps.courseware.date_summary import verified_upgrade_deadline_link
from lms.djangoapps.courseware.masquerade import setup_masquerade  # lint-amnesty, pylint: disable=unused-import
from openedx.core.djangoapps.content.course_overviews.models import CourseOverview  # lint-amnesty, pylint: disable=unused-import
from openedx.core.djangoapps.plugin_api.views import EdxFragmentView
from openedx.core.djangoapps.schedules.utils import reset_self_paced_schedule  # lint-amnesty, pylint: disable=unused-import
from openedx.features.course_experience import RELATIVE_DATES_FLAG  # lint-amnesty, pylint: disable=unused-import
from openedx.features.course_experience.utils import dates_banner_should_display
from openedx.features.content_type_gating.models import ContentTypeGatingConfig  # lint-amnesty, pylint: disable=unused-import
from common.djangoapps.student.models import CourseEnrollment
from common.djangoapps.util.milestones_helpers import get_course_content_milestones
from common.djangoapps.credo_modules.models import Organization
from xmodule.course_module import COURSE_VISIBILITY_PUBLIC
from xmodule.modulestore.django import modulestore

from ..utils import get_course_outline_block_tree, get_resume_block

DEFAULT_COMPLETION_TRACKING_START = datetime.datetime(2018, 1, 24, tzinfo=UTC)
log = logging.getLogger(__name__)


class CourseOutlineFragmentView(EdxFragmentView):
    """
    Course outline fragment to be shown in the unified course view.
    """
    def __init__(self, *args, **kwargs):
        super(CourseOutlineFragmentView, self).__init__(*args, **kwargs)
        self.featured_desc_limit = 110
        self.featured_title_limit = 30

    def _convert_complete_status(self, status):
        if status == 'not_started':
            return 'begin', 'Begin'
        elif status == 'in_progress':
            return 'in-progress', 'In progress'
        elif status == 'finished':
            return 'complete', 'Completed!'
        return 'begin', status

    def find_rev(self, str, target, start):
        str = str[::-1]
        index = str.find(target, len(str) - start)
        if index != -1:
            index = len(str) - index
        return index

    def str_limit(self, title, limit):
        if len(title) <= limit: return title
        cut = self.find_rev(title, ' ', limit - 3 + 1)
        if cut != -1:
            title = title[:cut - 1] + "..."
        else:
            title = title[:limit - 3] + "..."
        return title

    def get_featured_map(self, course_key):
        tiles = modulestore().get_items(course_key,
                                        settings={'top_of_course_outline': True},
                                        qualifiers={'category': 'sequential'})
        tiles = dict([(str(sub.location), sub) for sub in tiles])
        return tiles

    def get_not_display_items(self, course_key):
        items = modulestore().get_items(course_key,
                                        settings={'do_not_display_in_course_outline': True},
                                        qualifiers={'category': 'sequential'})
        items = [str(item.location) for item in items]
        return items

    def render_to_fragment(self, request, course_id, user_is_enrolled=True, **kwargs):  # pylint: disable=arguments-differ
        """
        Renders the course outline as a fragment.
        """
        from lms.urls import RESET_COURSE_DEADLINES_NAME
        from openedx.features.course_experience.urls import COURSE_HOME_VIEW_NAME  # lint-amnesty, pylint: disable=unused-import

        course_key = CourseKey.from_string(course_id)
        course_overview = get_course_overview_with_access(
            request.user, 'load', course_key, check_if_enrolled=user_is_enrolled
        )
        course = modulestore().get_course(course_key)
        template = 'course_experience/course-outline-fragment.html'

        course_block_tree = get_course_outline_block_tree(
            request, course_id, request.user if user_is_enrolled else None
        )
        if not course_block_tree:
            return None

        try:
            org = Organization.objects.get(org=course.org)
        except Organization.DoesNotExist:
            org = None

        highlighted_blocks = []
        if org and org.is_carousel_view:
            top_sequential_blocks = []
            filtered_course_tree = []
            status_map = {}
            featured_map = self.get_featured_map(course_key)
            not_display_outline = self.get_not_display_items(course_key)

            updated_course_children = []
            for num_sub, sub in enumerate(course_block_tree.get('children', []), 1):
                filtered_course_tree.append(sub)
                num_completed = 0
                sub['num_children'] = len(sub.get('children', []))
                sub['jump_to'] = reverse(
                        'jump_to',
                        kwargs={'course_id': str(course_key), 'location': sub['id']},
                    )
                updated_children_subs = []
                for i in sub.get('children', []):
                    # show in featured block
                    if i['id'] in featured_map:
                        top_sequential_blocks.append(featured_map[i['id']])

                    complete_status = i.get('complete_status')
                    status_map[i['id']] = complete_status

                    if complete_status == 'finished':
                        num_completed += 1

                    i['jump_to'] = reverse(
                        'jump_to', kwargs={'course_id': str(course_key), 'location': i['id']},)

                    if i['id'] not in not_display_outline:
                        updated_children_subs.append(i)

                if len(updated_children_subs) > 0:
                    sub['children'] = updated_children_subs
                    sub['num_completed'] = num_completed
                    updated_course_children.append(sub)
            course_block_tree['children'] = updated_course_children

            for i, item in enumerate(top_sequential_blocks, start=1):
                progress_status, progress_status_tilte = self._convert_complete_status(
                    status_map.get(str(item.location)))
                jump_item = item
                highlighted_blocks.append({
                    'index': i,
                    'desc': self.str_limit(item.course_outline_description, self.featured_desc_limit),
                    'btn_title': item.course_outline_button_title,
                    'status': progress_status,
                    'status_title': progress_status_tilte,
                    'display_name': self.str_limit(item.display_name, self.featured_title_limit),
                    'jump_to': reverse(
                        'jump_to', kwargs={'course_id': str(course_key), 'location': str(jump_item.location)},
                    ),
                })
            template = 'course_experience/course-outline-highlighted-fragment.html'

        resume_block = get_resume_block(course_block_tree) if user_is_enrolled else None

        if not resume_block:
            self.mark_first_unit_to_resume(course_block_tree)

        xblock_display_names = self.create_xblock_id_and_name_dict(course_block_tree)
        gated_content = self.get_content_milestones(request, course_key)

        missed_deadlines, missed_gated_content = dates_banner_should_display(course_key, request.user)

        reset_deadlines_url = reverse(RESET_COURSE_DEADLINES_NAME)

        context = {
            'csrf': csrf(request)['csrf_token'],
            'course': course_overview,
            'due_date_display_format': course.due_date_display_format,
            'blocks': course_block_tree,
            'highlighted_blocks': highlighted_blocks,
            'enable_links': user_is_enrolled or course.course_visibility == COURSE_VISIBILITY_PUBLIC,
            'course_key': course_key,
            'gated_content': gated_content,
            'xblock_display_names': xblock_display_names,
            'self_paced': course.self_paced,

            # We're using this flag to prevent old self-paced dates from leaking out on courses not
            # managed by edx-when.
            'in_edx_when': edx_when_api.is_enabled_for_course(course_key),
            'reset_deadlines_url': reset_deadlines_url,
            'verified_upgrade_link': verified_upgrade_deadline_link(request.user, course=course),
            'on_course_outline_page': True,
            'missed_deadlines': missed_deadlines,
            'missed_gated_content': missed_gated_content,
            'has_ended': course.has_ended(),
        }

        html = render_to_string(template, context)
        return Fragment(html)

    def create_xblock_id_and_name_dict(self, course_block_tree, xblock_display_names=None):
        """
        Creates a dictionary mapping xblock IDs to their names, using a course block tree.
        """
        if xblock_display_names is None:
            xblock_display_names = {}

        if not course_block_tree.get('authorization_denial_reason'):
            if course_block_tree.get('id'):
                xblock_display_names[course_block_tree['id']] = course_block_tree['display_name']

            if course_block_tree.get('children'):
                for child in course_block_tree['children']:
                    self.create_xblock_id_and_name_dict(child, xblock_display_names)

        return xblock_display_names

    def get_content_milestones(self, request, course_key):
        """
        Returns dict of subsections with prerequisites and whether the prerequisite has been completed or not
        """
        def _get_key_of_prerequisite(namespace):
            return re.sub('.gating', '', namespace)

        all_course_milestones = get_course_content_milestones(course_key)

        uncompleted_prereqs = {
            milestone['content_id']
            for milestone in get_course_content_milestones(course_key, user_id=request.user.id)
        }

        gated_content = {
            milestone['content_id']: {
                'completed_prereqs': milestone['content_id'] not in uncompleted_prereqs,
                'prerequisite': _get_key_of_prerequisite(milestone['namespace'])
            }
            for milestone in all_course_milestones
        }

        return gated_content

    def user_enrolled_after_completion_collection(self, user, course_key):
        """
        Checks that the user has enrolled in the course after 01/24/2018, the date that
        the completion API began data collection. If the user has enrolled in the course
        before this date, they may see incomplete collection data. This is a temporary
        check until all active enrollments are created after the date.
        """
        user = User.objects.get(username=user)
        try:
            user_enrollment = CourseEnrollment.objects.get(
                user=user,
                course_id=course_key,
                is_active=True
            )
            return user_enrollment.created > self._completion_data_collection_start()
        except CourseEnrollment.DoesNotExist:
            return False

    def _completion_data_collection_start(self):
        """
        Returns the date that the ENABLE_COMPLETION_TRACKING waffle switch was enabled.
        """
        try:
            return Switch.objects.get(name=ENABLE_COMPLETION_TRACKING_SWITCH.name).created
        except Switch.DoesNotExist:
            return DEFAULT_COMPLETION_TRACKING_START

    def mark_first_unit_to_resume(self, block_node):
        children = block_node.get('children')
        if children:
            children[0]['resume_block'] = True
            self.mark_first_unit_to_resume(children[0])
