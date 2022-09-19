import datetime
import pytz
from collections import namedtuple
from bs4 import BeautifulSoup
from django.utils.html import strip_tags
from django.contrib.auth import get_user_model
from common.djangoapps.credo_modules.models import TrackingLogUserInfo


User = get_user_model()
CorrectData = namedtuple('CorrectData', ['is_correct', 'earned_grade', 'max_grade', 'correctness'])


class Gender:
    key = 'gender'
    map = {
        'm': 'Male',
        'f': 'Female',
        'o': 'Other'
    }


class EventCategory:
    problem = 'problem'
    ora = 'ora'
    ora_empty_rubrics = 'ora-empty-rubrics'
    dnd = 'dnd'
    viewed = 'viewed'
    image_explorer = 'image-explorer'
    text_highlighter = 'text-highlighter'
    freetextresponse = 'freetextresponse'


EXCLUDE_PROPERTIES = [
    "gender", "context_id", "course_section",
    "email", "firstname", "lastname", "first_name", "last_name", "name", "surname",
    "student_email", "studentemail", "student_firstname", "studentfirstname",
    "studentlastname", "student_lastname", "studentname", "student_name",
    "user", "user_full_name", "user_email",
    "term", "terms", "run", "runs"
]

COURSE_PROPERTIES = [
    'course', 'courses',
    'course_title', 'course title',
    'course_name', 'course name', 'coursename',
    'othercourse', 'course name/number'
]

INSIGHTS_COURSE_STAFF_ROLES = [
    'instructor', 'staff', 'beta_testers', 'data_researcher',
    'finance_admin', 'sales_admin', 'course_creator_group', 'support'
]

INSIGHTS_ORG_STAFF_ROLES = [
    'instructor', 'staff'
]


def filter_properties(props_dict):
    for pr_to_remove in EXCLUDE_PROPERTIES:
        if pr_to_remove in props_dict:
            props_dict.pop(pr_to_remove, None)
    return props_dict


def get_timestamp_from_datetime(dt):
    dt = dt.replace(tzinfo=pytz.utc)
    dt2 = dt - datetime.datetime(1970, 1, 1).replace(tzinfo=pytz.utc)
    return int(dt2.total_seconds())


def get_answer_from_text(answers_text):
    answers_wo_tags = strip_tags(answers_text)
    answers_wo_tags = answers_wo_tags.strip()
    if answers_wo_tags:
        return answers_wo_tags
    elif '<img' in answers_text:
        html_block = BeautifulSoup(answers_text)
        images = html_block.findAll('img')
        if len(images) > 0:
            img_item = images[0]
            img_title = ''
            try:
                img_attr_title = img_item['title']
                img_title = img_attr_title.strip()
            except KeyError:
                pass
            try:
                img_attr_alt = img_item['alt']
                img_title = img_attr_alt.strip()
            except KeyError:
                pass
            try:
                img_attr_src = img_item['src'].strip()
            except KeyError:
                return ''
            if '?' in img_attr_src:
                img_src = img_attr_src.split('?')[0].strip()
            else:
                img_src = img_attr_src.strip()
            if img_title:
                img_src = img_src + ' (' + img_title + ')'
            return img_src
    return ''


def get_prop_user_info(props_dict):
    email = None
    first_name = None
    last_name = None
    full_name = None

    emails_props = ['email', 'student_email', 'studentemail', 'user_email']
    for email_prop in emails_props:
        email = props_dict.get(email_prop)
        if email:
            break

    first_name_props = ['firstname', 'first_name', 'student_firstname', 'studentfirstname']
    for first_name_prop in first_name_props:
        first_name = props_dict.get(first_name_prop)
        if first_name:
            break

    last_name_props = ['lastname', 'last_name', 'surname', 'studentlastname', 'student_lastname']
    for last_name_prop in last_name_props:
        last_name = props_dict.get(last_name_prop)
        if last_name:
            break

    full_name_props = ['name', 'studentname', 'student_name', 'user', 'user_full_name']
    for full_name_prop in full_name_props:
        full_name = props_dict.get(full_name_prop)
        if full_name:
            break

    if not full_name:
        if first_name and last_name:
            full_name = first_name + ' ' + last_name
        elif first_name and not last_name:
            full_name = first_name
        elif not first_name and last_name:
            full_name = last_name

    return email, full_name


def prepare_text_for_column_db(txt, char_num=5000):
    txt = txt.rstrip('\\').strip().replace("\n", " ").replace("\t", " ").replace('"', '\'').replace("|", " ")
    txt = txt.encode('utf-8').decode('ascii', errors='ignore')
    if len(txt) > char_num:
        char_num = char_num - 4
        txt = txt[:char_num] + '...'
    return txt


def pull_value_from_student_properties(key, properties):
    key_updated = key.strip().lower()
    new_value = None
    new_properties = properties.copy()

    tmp_properties = {}
    for k in new_properties:
        tmp_properties[k.strip().lower()] = k
    for tk, tv in tmp_properties.items():
        if tk == key_updated:
            new_value = new_properties[tv].replace('+', '-') \
                    .replace("\n", "").replace("\t", "").replace("\r", "").replace("|", " ")
            del new_properties[tv]
    return new_value, new_properties


def update_course_and_student_properties(course, student_properties):
    overload_items = {
        'course': {
            'value': course,
            'props': ['course', 'courses', 'course_title', 'course title',
                      'course_name', 'course name', 'coursename', 'othercourse']
        },
    }
    for k in overload_items:
        for prop in overload_items[k]['props']:
            new_value, new_properties = pull_value_from_student_properties(prop, student_properties)
            if new_value:
                overload_items[k]['value'], student_properties = new_value, new_properties

    return overload_items['course']['value'], student_properties


def combine_student_properties(props):
    result = {}
    tmp_result = {}
    types = ['registration', 'enrollment']
    for tp in types:
        tmp_result.update(props.get(tp, {}))
    for prop_key, prop_value in tmp_result.items():
        prop_value = prop_value.strip()
        if prop_value:
            if len(prop_value) > 255:
                prop_value = prop_value[0:255]
            result[prop_key.lower()] = prop_value
    return result


def parse_course_id(course_id):
    return list(course_id[len('course-v1:'):].split('+') + ([None] * 3))[:3]


def update_user_info(org_id, user_id, prop_email, prop_full_name, users_processed_cache):
    token = org_id + '|' + str(user_id)
    create_new = False

    if token in users_processed_cache:
        log_user_info = users_processed_cache[token]
    else:
        try:
            log_user_info = TrackingLogUserInfo.objects.get(org_id=org_id, user_id=user_id)
            users_processed_cache[token] = log_user_info
        except TrackingLogUserInfo.DoesNotExist:
            log_user_info = TrackingLogUserInfo(org_id=org_id, user_id=user_id)
            create_new = True

    email_to_set = ''
    full_name_to_set = ''

    if create_new:
        try:
            user = User.objects.get(id=user_id)
            email_to_set = user.email
            if user.first_name and user.last_name:
                full_name_to_set = user.first_name + ' ' + user.last_name
            elif user.first_name and not user.last_name:
                full_name_to_set = user.first_name
            elif not user.first_name and user.last_name:
                full_name_to_set = user.last_name
        except User.DoesNotExist:
            pass

    if prop_email:
        email_to_set = prop_email
    if prop_full_name:
        full_name_to_set = prop_full_name

    changed = False
    if email_to_set and log_user_info.email != email_to_set:
        log_user_info.email = email_to_set
        changed = True
    if full_name_to_set and log_user_info.full_name != full_name_to_set:
        log_user_info.full_name = full_name_to_set
        changed = True

    if create_new or changed:
        log_user_info.update_search_token()
        log_user_info.save()
        if create_new:
            users_processed_cache[token] = log_user_info


def ora_is_graded(event):
    event_data = event.get('event', {})
    if 'is_additional_rubric' in event_data and 'ungraded' in event_data:
        is_additional_rubric = event_data.get('is_additional_rubric', None)
        ungraded = event_data.get('ungraded', None)
        if is_additional_rubric is True and ungraded is True:
            return False
    return None
