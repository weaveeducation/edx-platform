import hashlib
import logging
import json

from collections import OrderedDict
from lms.djangoapps.courseware.courses import get_course_by_id
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from django.http import Http404, HttpResponseBadRequest, JsonResponse
from django.shortcuts import redirect, reverse, NoReverseMatch
from django.urls import resolve
from django.core.exceptions import PermissionDenied
from django.contrib.auth import login
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.views.generic.base import View
from django.views.decorators.http import require_http_methods
from django.views.decorators.clickjacking import xframe_options_exempt
from django.contrib.auth.decorators import login_required
from django.utils.http import urlunquote
from django.utils.decorators import method_decorator
from django.utils.translation import ugettext_lazy as _
from django.shortcuts import render
from common.djangoapps.credo_modules.models import CredoModulesUserProfile, Organization, OrganizationTag, OrganizationTagOrder
from common.djangoapps.credo_modules.utils import additional_profile_fields_hash
from common.djangoapps.util.json_request import JsonResponse
from openedx.core.djangoapps.site_configuration import helpers as configuration_helpers

from common.djangoapps.edxmako.shortcuts import render_to_response
from opaque_keys.edx.keys import CourseKey


log = logging.getLogger(__name__)
User = get_user_model()

GROUPED_ORGANIZATION_TAGS = [
    'AAC&U VALUE Rubric'
]


class StudentProfileField:

    alias = ""
    required = False
    title = ""
    default = ""
    options = []
    order = None

    def __init__(self, alias="", required=False, title="", default="", options=None, allow_non_suggested=False,
                 order=None, info=False, hidden=False, minlength=None, maxlength=None,
                 minnumber=None, maxnumber=None, isnumber=None, isalnum=False):
        self.alias = alias
        self.required = required
        self.title = title
        self.default = str(default) if default is not None else None
        self.options = options
        self.allow_non_suggested = allow_non_suggested
        self.order = order
        self.info = info
        self.hidden = hidden
        self.minnumber = str(minnumber) if minnumber is not None else None
        self.maxnumber = str(maxnumber) if maxnumber is not None else None
        self.minlength = str(minlength) if minlength is not None else None
        self.maxlength = str(maxlength) if maxlength is not None else None
        self.isnumber = isnumber
        self.isalnum = isalnum

    @classmethod
    def init_from_course(cls, course, default_fields=None):
        res_unsorted = OrderedDict()
        for k, v in course.credo_additional_profile_fields.items():
            order = None
            try:
                order = int(v['order']) if 'order' in v else None
            except ValueError:
                pass

            allow_non_suggested = None
            options = v['options'] if 'options' in v and v['options'] else None
            if options:
                allow_non_suggested = v['allow_non_suggested'] if 'allow_non_suggested' in v else None
                if allow_non_suggested:
                    options.append('Other')

            minlength = None
            maxlength = None
            minnumber = None
            maxnumber = None
            isnumber = None
            isalnum = False

            default_tmp = default_fields[k].encode('utf-8')\
                if default_fields and (k in default_fields) else v.get('default')
            if options:
                if not default_tmp or default_tmp in options:
                    default = default_tmp
                else:
                    default = 'Other'
            else:
                default = default_tmp

                validation = v.get('validation', {})
                minlength = validation.get('string', {}).get('min', None)
                maxlength = validation.get('string', {}).get('max', None)
                isalnum = validation.get('string', {}).get('alnum', False)
                minnumber = validation.get('number', {}).get('min', None)
                maxnumber = validation.get('number', {}).get('max', None)

                if minlength:
                    try:
                        minlength = int(minlength)
                    except ValueError:
                        minlength = None

                if maxlength:
                    try:
                        maxlength = int(maxlength)
                    except ValueError:
                        maxlength = None

                if minnumber:
                    try:
                        minnumber = int(minnumber)
                    except ValueError:
                        minnumber = None

                if maxnumber:
                    try:
                        maxnumber = int(maxnumber)
                    except ValueError:
                        maxnumber = None

                isalnum = True if isalnum else False

                isnumber = 'number' in validation
                if isnumber:
                    minlength = None
                    maxlength = None
                    isalnum = False
                    try:
                        default = int(default)
                    except ValueError:
                        default = None

                    if minnumber is not None and default is not None and default < minnumber:
                        default = None
                    elif maxnumber is not None and default is not None and default > maxnumber:
                        default = None

            kwargs = {
                'alias': k,
                'required': v['required'] if 'required' in v and v['required'] else False,
                'title': v['title'] if 'title' in v and v['title'] else k,
                'default': default,
                'options': options,
                'allow_non_suggested': allow_non_suggested,
                'order': order,
                'info': bool(v.get('info')),
                'hidden': False,
                'minlength': minlength,
                'maxlength': maxlength,
                'minnumber': minnumber,
                'maxnumber': maxnumber,
                'isnumber': isnumber,
                'isalnum': isalnum
            }
            res_unsorted[k] = StudentProfileField(**kwargs)

            if options and allow_non_suggested:
                kk = k + '__custom'
                kwargs = {
                    'alias': kk,
                    'required': False,
                    'title': 'Please describe',
                    'default': default_tmp if default == 'Other' and default_tmp else '',
                    'options': None,
                    'allow_non_suggested': None,
                    'order': order + 0.5,
                    'info': False,
                    'hidden': False if default == 'Other' and default_tmp else True,
                    'minlength': None,
                    'maxlength': None,
                    'minnumber': None,
                    'maxnumber': None,
                    'isnumber': None,
                    'isalnum': None
                }
                res_unsorted[kk] = StudentProfileField(**kwargs)
        return OrderedDict(sorted(res_unsorted.items(), key=lambda t: t[1].order if t[1].order is not None else t[0]))


def show_student_profile_form(request, course, simple_layout=False, redirect_to=None):
    course_key = course.id

    profiles = CredoModulesUserProfile.objects.filter(user=request.user, course_id=course_key)
    if len(profiles) > 0:
        profile = profiles[0]
        profile_fields = json.loads(profile.meta)
    else:
        profile_fields = {}

    fields = StudentProfileField.init_from_course(course, profile_fields)
    context = {
        'fields': fields.values(),
        'redirect_url': redirect_to if redirect_to else '',
        'course_id': str(course.id),
    }
    if simple_layout:
        context.update({
            'disable_accordion': True,
            'allow_iframing': True,
            'disable_header': True,
            'disable_footer': True,
            'disable_window_wrap': True,
            'disable_preview_menu': True,
        })

    return render_to_response("credo_additional_profile.html", context)


class StudentProfileView(View):

    @method_decorator(login_required)
    @method_decorator(xframe_options_exempt)
    @method_decorator(transaction.atomic)
    def get(self, request, course_id):
        redirect_to = request.GET.get('next', None)
        course_key = CourseKey.from_string(course_id)
        course = get_course_by_id(course_key)
        simple_layout = False
        views_with_simple_layout = ('render_xblock_course', 'lti_launch')

        if not course.credo_additional_profile_fields:
            if not redirect_to:
                try:
                    redirect_to = reverse('dashboard')
                except NoReverseMatch:
                    redirect_to = reverse('home')
            else:
                redirect_to = urlunquote(redirect_to)
            return redirect(redirect_to)

        if redirect_to:
            try:
                redirect_url_info = resolve(redirect_to)
                if redirect_url_info.view_name in views_with_simple_layout:
                    simple_layout = True
            except Http404:
                pass

        return show_student_profile_form(request, course, simple_layout=simple_layout, redirect_to=redirect_to)

    def _is_valid(self, value, field):
        if field.isnumber:
            try:
                value = int(value)
            except ValueError:
                return False, ''.join([field.title, " field must be digit"])
            if field.minnumber is not None and value < int(field.minnumber):
                return False, ''.join([field.title, " field must be greater or equal than ", str(field.minnumber)])
            if field.maxnumber is not None and value > int(field.maxnumber):
                return False, ''.join([field.title, " field must be less or equal than ", str(field.maxnumber)])
        else:
            if field.minlength is not None and len(value) < int(field.minlength):
                return False, ''.join([field.title, " field must contains at least %s characters"
                                       % str(field.minlength)])
            if field.maxlength is not None and len(value) > int(field.maxlength):
                return False, ''.join([field.title, " field must contains at most %s characters"
                                       % str(field.maxlength)])
            if field.isalnum and not value.isalnum():
                return False, ''.join([field.title, " field must contains only letters and digits"])
        return True, None

    @method_decorator(login_required)
    @method_decorator(transaction.atomic)
    def post(self, request, course_id):
        course_key = CourseKey.from_string(course_id)
        course = get_course_by_id(course_key)

        if not course.credo_additional_profile_fields:
            return JsonResponse({}, status=404)
        else:
            data = request.POST.copy()
            fields_version = additional_profile_fields_hash(course.credo_additional_profile_fields)

            to_save_fields = {}
            errors = {}
            form_fields = StudentProfileField.init_from_course(course)

            fields_to_replace = []

            for field_alias, field in form_fields.items():
                if field.info:
                    continue
                passed_field = data.get(field_alias, '')
                if not passed_field and field.required:
                    errors[field_alias] = ''.join([field.title, " field is required"])
                else:
                    is_valid, err_msg = self._is_valid(data.get(field_alias, ''), field)
                    if is_valid:
                        to_save_fields[field_alias] = passed_field
                        if field_alias.endswith('__custom'):
                            fields_to_replace.append(field_alias)
                    else:
                        errors[field_alias] = err_msg

            for field_to_replace in fields_to_replace:
                original_field_name = field_to_replace[0:-len('__custom')]
                if data[original_field_name] == 'Other':
                    to_save_fields[original_field_name] = data[field_to_replace]
                else:
                    to_save_fields[original_field_name] = data[original_field_name]
                to_save_fields.pop(field_to_replace)

            if errors:
                return JsonResponse(errors, status=400)
            else:
                to_save_fields_json = json.dumps(to_save_fields, sort_keys=True)
                profiles = CredoModulesUserProfile.objects.filter(user=request.user, course_id=course_key)

                if len(profiles) > 0:
                    profile = profiles[0]
                    profile.meta = to_save_fields_json
                    profile.fields_version = fields_version
                    profile.save()
                else:
                    profile = CredoModulesUserProfile(user=request.user, course_id=course_key,
                                                      meta=to_save_fields_json, fields_version=fields_version)
                    profile.save()
                return JsonResponse({"success": True})


@login_required
def login_as_user(request):
    if not request.user.is_superuser:
        return JsonResponse({
            "success": False,
            "errorMessage": "Invalid request"
        })

    word = request.GET.get('user', '')
    word = word.strip()
    if not word:
        return JsonResponse({
            "success": False,
            "errorMessage": "Invalid request"
        })

    edx_user = None
    if word.isdigit():
        try:
            edx_user = User.objects.get(id=int(word))
        except User.DoesNotExist:
            pass

    if not edx_user:
        try:
            edx_user = User.objects.get(Q(username=word) | Q(email=word))
        except User.DoesNotExist:
            return JsonResponse({
                "success": False,
                "userid": None,
                "errorMessage": "User not found"
            })

    login(request, edx_user, backend=settings.AUTHENTICATION_BACKENDS[0])
    return redirect(reverse('dashboard'))


def _manage_org_tags_render_template(request, tpl, page_title, org, **kwargs):
    context = {
        "title": "Organization " + str(org.org) + '. ' + page_title,
        "site_title": _('Studio Administration'),
        "site_header": _('Studio Administration'),
        "user": request.user,
        "has_permission": True,
        "site_url": "/",
    }
    context.update(kwargs)
    return render(request, tpl, context)


def _parse_tag(t, org, insights, skills):
    tag_org = t.get('obj')
    tag_id = t.get('id')
    tag_name = t.get('name')
    insights_view = tag_id in insights
    progress_view = tag_id in skills
    if not tag_org:
        tag_org = OrganizationTag(
            org=org,
            tag_name=tag_name,
            insights_view=insights_view,
            progress_view=progress_view
        )
        tag_org.save()
    elif insights_view != tag_org.insights_view or progress_view != tag_org.progress_view:
        tag_org.insights_view = insights_view
        tag_org.progress_view = progress_view
        tag_org.save()
    return tag_org


def _manage_org_tags_update_data(request, org, tags_result):
    OrganizationTag.objects.filter(org=org, tag_name__in=GROUPED_ORGANIZATION_TAGS).delete()

    request_insights = request.POST.getlist('insights')
    request_skills = request.POST.getlist('skills')
    tag_ids = []

    for tag in tags_result:
        if 'children' in tag:
            for child_tag in tag['children']:
                parsed_tag = _parse_tag(child_tag, org, request_insights, request_skills)
                tag_ids.append(parsed_tag.id)
        else:
            parsed_tag = _parse_tag(tag, org, request_insights, request_skills)
            tag_ids.append(parsed_tag.id)

    query_to_remove = OrganizationTag.objects.filter(org=org)
    if tag_ids:
        query_to_remove = query_to_remove.exclude(id__in=tag_ids)
    query_to_remove.delete()

    messages.success(request, _("Tags successfully saved"))
    current_url = reverse('admin-manage-org-tags', kwargs={
        "org_id": org.id
    })
    return redirect(current_url)


def _get_org(request, org_id):
    try:
        from cms.lib.xblock.tagging.models import TagCategories, TagAvailableValues
    except (RuntimeError, ImportError):
        cms_base = configuration_helpers.get_value(
            'CMS_BASE',
            getattr(settings, 'CMS_BASE', 'localhost')
        )
        if settings.DEBUG:
            cms_base = 'http://' + cms_base
        else:
            cms_base = 'https://' + cms_base
        cms_url = cms_base + reverse('admin-manage-org-tags', kwargs={
            "org_id": org_id
        })
        return None, None, redirect(cms_url)

    if not request.user.is_authenticated or not request.user.is_staff:
        raise PermissionDenied()

    try:
        org = Organization.objects.get(id=org_id)
    except Organization.DoesNotExist:
        log.error("Org with ID=%s doesn't exist" % str(org_id))
        raise Http404

    org_type_id = None
    if org.org_type is not None:
        org_type_id = org.org_type.id

    tag_category_ids = []

    if org_type_id:
        tag_categories = TagCategories.objects.filter(Q(org_types__org_type=None) | Q(org_types__org_type=org_type_id))
        tag_category_ids = [t_cat.id for t_cat in tag_categories]

    if tag_category_ids:
        tag_available_values = TagAvailableValues.objects.filter(category_id__in=tag_category_ids).order_by('value')
    else:
        tag_available_values = TagAvailableValues.objects.all().order_by('value')

    return tag_available_values, org, None


def _generate_tag_item(value, title, tag):
    return {
        'name': value,
        'title': title,
        'insights_view': tag.get('insights_view', True),
        'progress_view': tag.get('progress_view', True),
        'obj': tag.get('obj'),
        'id': hashlib.md5(value.encode('utf-8')).hexdigest()
    }


def _sort_tag_items_by_title(tags):
    return sorted(tags, key=lambda v: v['title'])


@login_required
@require_http_methods(["GET", "POST"])
def manage_org_tags(request, org_id):
    tag_available_values, org, http_redirect = _get_org(request, org_id)
    if not org:
        return http_redirect

    tags_dict = {}
    tags = OrganizationTag.objects.filter(org=org)
    for tag in tags:
        tags_dict[tag.tag_name] = {
            'insights_view': tag.insights_view,
            'progress_view': tag.progress_view,
            'obj': tag
        }

    tags_result_dict = {}
    for tag in tag_available_values:
        if tag.org and tag.org != org.org:
            continue

        tag_value = tag.value.strip()
        tag_value_keys = tag_value.split(' - ')
        tag_root_key = tag_value_keys[0].strip()
        tag_child_key = tag_value_keys[1] if len(tag_value_keys) > 1 else None

        if tag_child_key and tag_root_key in GROUPED_ORGANIZATION_TAGS:
            parent = tags_result_dict.get(tag_root_key, {
                'title': tag_root_key,
                'children': {},
                'insights_view': True,
                'progress_view': True
            })
            if tag_child_key in parent['children']:
                continue
            tag_child_value = tag_root_key + ' - ' + tag_child_key
            child = _generate_tag_item(tag_child_value, tag_child_key, tags_dict.get(tag_child_value, {}))
            if parent['insights_view']:
                parent['insights_view'] = child['insights_view']
            if parent['progress_view']:
                parent['progress_view'] = child['progress_view']
            parent['children'][tag_child_key] = child
            tags_result_dict[tag_root_key] = parent
        elif tag_root_key not in tags_result_dict:
            item = _generate_tag_item(tag_root_key, tag_root_key, tags_dict.get(tag_root_key, {}))
            tags_result_dict[tag_root_key] = item

    tags_result = _sort_tag_items_by_title(tags_result_dict.values())

    for item in tags_result:
        if 'children' in item:
            item['children'] = _sort_tag_items_by_title(item['children'].values())

    if request.method == 'GET':
        return _manage_org_tags_render_template(request, 'admin/configure_tags_for_org.html',
                                                'Configure Tags', org, tags_result=tags_result)
    elif request.method == 'POST':
        return _manage_org_tags_update_data(request, org, tags_result)
    else:
        return HttpResponseBadRequest('Invalid request')


@login_required
@require_http_methods(["GET", "POST"])
def manage_org_tags_sorting(request, org_id):
    def _update_tags_dict(res, idx, tags_list):
        if idx + 1 <= len(tags_list):
            tag_new_val = ' - '.join(tags_list[0:idx + 1])
            if tag_new_val not in res:
                res[tag_new_val] = {
                    'id': tag_new_val,
                    'title': tags_list[0:idx + 1][-1],
                    'children': OrderedDict()
                }
            _update_tags_dict(res[tag_new_val]['children'], idx + 1, tags_list)

    def _convert_tags_dict_to_list(data):
        return [{'name': v['title'], 'id': v['id'], 'children': _convert_tags_dict_to_list(v['children'])}
                for k, v in data.items()]

    tag_available_values_raw, org, http_redirect = _get_org(request, org_id)
    if not org:
        return http_redirect

    tag_available_values = [t.value for t in tag_available_values_raw]

    tags_data_raw = OrganizationTagOrder.objects.filter(org=org).order_by('order_num', 'tag_name')
    tags_data = [t.tag_name for t in tags_data_raw]

    tags_result = OrderedDict()

    if request.method == 'GET':
        for tag_d in tags_data:
            tag_split_lst = tag_d.split(' - ')
            _update_tags_dict(tags_result, 0, tag_split_lst)
        for tag_av in tag_available_values:
            tag_split_lst = tag_av.split(' - ')
            _update_tags_dict(tags_result, 0, tag_split_lst)

        tags_lst = _convert_tags_dict_to_list(tags_result)

        return _manage_org_tags_render_template(request, "admin/configure_tags_order_for_org.html",
                                                "Configure Tags Order", org,
                                                tags_result=tags_result, tags_lst=tags_lst,
                                                tags_lst_str=json.dumps(tags_lst))
    elif request.method == 'POST':
        req_tags_data = json.loads(request.body.decode('utf8'))
        tags_to_insert = []
        idx = 10

        for tag_item in req_tags_data:
            if tag_item in tag_available_values:
                tags_to_insert.append(OrganizationTagOrder(
                    org=org,
                    tag_name=tag_item,
                    order_num=idx
                ))
                idx = idx + 10

        with transaction.atomic():
            OrganizationTagOrder.objects.filter(org=org).delete()
            OrganizationTagOrder.objects.bulk_create(tags_to_insert)

        messages.success(request, _("Tags order successfully saved"))
        return JsonResponse({'success': True})
    else:
        return HttpResponseBadRequest('Invalid request')
