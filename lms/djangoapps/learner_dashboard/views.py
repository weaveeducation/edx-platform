"""Learner dashboard views"""


from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_GET

from edxmako.shortcuts import render_to_response
from lms.djangoapps.learner_dashboard.programs import ProgramDetailsFragmentView, ProgramsFragmentView
from openedx.core.djangoapps.programs.models import ProgramsApiConfig
from credo_modules.models import check_my_skills_access


@login_required
@require_GET
def program_listing(request):
    """View a list of programs in which the user is engaged."""
    programs_config = ProgramsApiConfig.current()
    programs_fragment = ProgramsFragmentView().render_to_fragment(request, programs_config=programs_config)

    context = {
        'disable_courseware_js': True,
        'programs_fragment': programs_fragment,
        'nav_hidden': True,
        'show_dashboard_tabs': True,
        'show_program_listing': programs_config.enabled,
        'show_my_skills': check_my_skills_access(request.user),
        'uses_bootstrap': True,
    }

    return render_to_response('learner_dashboard/programs.html', context)


@login_required
@require_GET
def program_details(request, program_uuid):
    """View details about a specific program."""
    programs_config = ProgramsApiConfig.current()
    program_fragment = ProgramDetailsFragmentView().render_to_fragment(
        request, program_uuid, programs_config=programs_config
    )

    context = {
        'program_fragment': program_fragment,
        'show_dashboard_tabs': True,
        'show_program_listing': programs_config.enabled,
        'show_my_skills': check_my_skills_access(request.user),
        'nav_hidden': True,
        'disable_courseware_js': True,
        'uses_bootstrap': True,
    }

    return render_to_response('learner_dashboard/program_details.html', context)
