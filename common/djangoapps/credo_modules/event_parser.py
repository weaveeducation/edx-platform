import datetime
import hashlib
import json
import time
import re
import pytz
from collections import namedtuple


CorrectData = namedtuple('CorrectData', ['is_correct', 'earned_grade', 'max_grade', 'correctness'])


class Gender(object):
    key = 'gender'
    map = {
        'm': 'Male',
        'f': 'Female',
        'o': 'Other'
    }


def convert_properties(props_dict):
    if Gender.key in props_dict and props_dict[Gender.key] in Gender.map:
        props_dict[Gender.key] = Gender.map[props_dict[Gender.key]]
    return props_dict


class EventCategory(object):
    problem = 'problem'
    ora = 'ora'
    ora_empty_rubrics = 'ora-empty-rubrics'
    dnd = 'dnd'
    viewed = 'viewed'
    image_explorer = 'image-explorer'


class EventProcessor(object):

    @classmethod
    def process(cls, event_type, event_data):
        parser = {
            'problem_check': lambda: ProblemParser(),
            'edx.drag_and_drop_v2.item.dropped': lambda: DndParser(),
            'openassessmentblock.create_submission': lambda: OraWithoutCriteriaParser(),
            'openassessmentblock.staff_assess': lambda: OraParser(),
            'sequential_block.viewed': lambda: ViewedParser(),
            'sequential_block.remove_view': lambda: ViewedParser(),
            'xblock.image-explorer.hotspot.opened': lambda: ImageExplorerParser(),
        }.get(event_type, lambda: None)()

        if not parser:
            return None

        return parser.parse(event_data)


class EventData(object):
    def __init__(self, category, course_id, org_id, course, run, block_id,
                 timestamp, real_timestamp, saved_tags, student_properties,
                 grade, max_grade, user_id, display_name, question_text, question_hash, question_text_hash,
                 answers, submit_info=None, is_ora_empty_rubrics=False, is_block_view=False, possible_points=None,
                 ora_block=False, is_new_attempt=False, block_seq=None, is_staff=False, criterion_name=None,
                 correctness=None):
        self.category = category
        self.course_id = course_id
        self.course = course
        self.org_id = org_id
        self.run = run
        self.block_id = block_id
        self.timestamp = timestamp
        self.real_timestamp = real_timestamp
        self.saved_tags = saved_tags
        self.student_properties = student_properties
        self.grade = grade
        self.max_grade = max_grade
        self.user_id = user_id
        self.display_name = display_name.replace("\n", " ").replace("\t", " ") if display_name else ""
        self.question_text = question_text.replace("\n", " ").replace("\t", " ") if question_text else ""
        self.question_hash = question_hash
        self.question_text_hash = question_text_hash
        self.answers = answers.replace("\n", " ").replace("\t", " ") if answers else ""
        self.submit_info = submit_info
        self.is_ora_empty_rubrics = is_ora_empty_rubrics
        self.is_block_view = is_block_view
        self.possible_points = possible_points
        self.ora_block = ora_block
        self.is_new_attempt = is_new_attempt
        self.block_seq = block_seq
        self.is_staff = is_staff
        self.criterion_name = criterion_name
        self.correctness = correctness

    def __str__(self):
        sb = []
        for key in self.__dict__:
            v = self.__dict__[key]
            sb.append(key + '=' + v)
        return '<EventData ' + ', '.join(sb) + '>'

    @property
    def parsed_submit_info(self):
        return json.loads(self.submit_info) if self.submit_info else None

    @property
    def term(self):
        return self.student_properties.get('terms', None) if self.student_properties else None

    @property
    def ora_with_rubrics(self):
        return not self.is_ora_empty_rubrics and self.ora_block

    def get_earned_points(self):
        return sum([ans['points'] for ans in self.answers])


class EventParser(object):

    def process(self, event, *args, **kwargs):
        event_data = self.get_event_data(event)
        if event_data is None:
            return None

        timestamp = self.get_event_time_string(event)
        if timestamp is None:
            return None

        dtime = self.get_event_time(event)
        if dtime is None:
            return None
        dtime_ts = self.get_timestamp_from_datetime(dtime)

        course_id = self.get_course_id(event)
        user_id, is_staff = self.user_info(event)
        if not user_id:
            return None

        org_id = self.get_org_id_for_course(course_id)
        course = self.get_course_for_course(course_id)
        run = self.get_run_for_course(course_id)
        problem_id = self.get_problem_id(event, *args, **kwargs)

        if not self.custom_event_condition(event, *args, **kwargs):
            return None

        correct_data = self.get_correctness(event_data, *args, **kwargs)
        grade = self.get_grade(correct_data, *args, **kwargs)
        max_grade = correct_data.max_grade if correct_data else 0
        saved_tags = self.convert_tags(self.get_saved_tags(event, **kwargs))
        display_name = self.get_display_name(event, *args, **kwargs)
        question_text = self.get_question_text(event, *args, **kwargs)
        question_text_hash = self.get_question_text_hash(question_text)
        question_hash = self.get_question_hash(display_name, question_text)
        student_properties = convert_properties(self.get_student_properites(event))

        course, student_properties = self._update_course_and_student_properties(course, student_properties, dtime)

        answers = self.get_answers(event, correct_data, dtime_ts, grade=grade, *args, **kwargs)
        criterion_name = kwargs.get('criterion_name', None)
        correctness = correct_data.correctness if correct_data else None

        return EventData(
            category=self.get_category(event),
            course_id=course_id,
            org_id=org_id,
            course=course,
            run=run,
            block_id=problem_id,
            timestamp=timestamp,
            real_timestamp=dtime,
            saved_tags=saved_tags,
            student_properties=student_properties,
            grade=grade,
            max_grade=max_grade,
            user_id=user_id,
            display_name=display_name,
            question_text=question_text,
            question_hash=question_hash,
            question_text_hash=question_text_hash,
            answers=answers,
            is_ora_empty_rubrics=self.is_ora_empty_rubrics(event, *args, **kwargs),
            is_block_view=self.is_block_view(event, *args, **kwargs),
            possible_points=self.get_possible_points(event, *args, **kwargs),
            ora_block=self.is_ora_block(event, *args, **kwargs),
            is_new_attempt=self.is_new_attempt(event, *args, **kwargs),
            is_staff=is_staff,
            criterion_name=criterion_name,
            correctness=correctness
        )

    def user_info(self, event):
        user_id = self.get_student_id(event)
#        is_staff = is_staff_role(user_id, self.get_course_id(event))
        is_staff = False
        return user_id, is_staff

    def check_exclude_insights(self, user_id, course_id):
        pass

    def _update_course_and_student_properties(self, course, student_properties, dtime):
        overload_items = {
            'course': {'value': course, 'props': ['course', 'courses', 'course_title', 'course title', 'othercourse']},
            'term': {'value': None, 'props': ['term', 'terms', 'run', 'runs']}
        }
        for k in overload_items:
            for prop in overload_items[k]['props']:
                new_value, new_properties = self.pull_value_from_student_properties(prop, student_properties)
                if new_value:
                    overload_items[k]['value'], student_properties = new_value, new_properties
        student_properties['terms'] = overload_items['term']['value']
        if not student_properties['terms']:
            student_properties['terms'] = dtime.strftime("%B %Y")

        return overload_items['course']['value'], student_properties

    def convert_tags(self, saved_tags):
        tags_extended_lst = []
        for _, tag_val in saved_tags.items():
            tag_val_lst = [tag_val] if isinstance(tag_val, basestring) else tag_val
            for tag in tag_val_lst:
                tag_split_lst = tag.split(' - ')
                for idx, _ in enumerate(tag_split_lst):
                    tag_new_val = ' - '.join(tag_split_lst[0:idx + 1])
                    if tag_new_val not in tags_extended_lst:
                        tags_extended_lst.append(tag_new_val)
        return tags_extended_lst

    def pull_value_from_student_properties(self, key, properties):
        key_updated = key.strip().lower()
        new_value = None
        new_properties = properties.copy()

        tmp_properties = {}
        for k in new_properties:
            tmp_properties[k.strip().lower()] = k
        for tk, tv in tmp_properties.items():
            if tk == key_updated:
                new_value = new_properties[tv].replace('+', '-') \
                    .replace("\n", "").replace("\t", "").replace("\r", "")
                del new_properties[tv]
        return new_value, new_properties

    def get_student_properites(self, event):
        result = {}
        tmp = event.get('context').get('asides', {}).get('student_properties_aside', {}) \
            .get('student_properties', {})
        types = ['registration', 'enrollment']
        for tp in types:
            result.update(tmp.get(tp, {}))
        return result

    def get_saved_tags(self, event, **kwargs):
        # pylint: disable=unused-argument
        saved_tags = event.get('context').get('asides', {}).get('tagging_aside', {}).get('saved_tags', {})
        return saved_tags

    def get_run_for_course(self, course_id):
        try:
            return course_id[len('course-v1:'):].split('+')[2]
        except IndexError:
            return None

    def get_course_for_course(self, course_id):
        try:
            return course_id[len('course-v1:'):].split('+')[1]
        except IndexError:
            return None

    def get_org_id_for_course(self, course_id):
        """
        Args:
            course_id(unicode): The identifier for the course.

        Returns:
            The org_id extracted from the course_id, or None if none is found.
        """

        try:
            # course_key = CourseKey.from_string(course_id)
            # return course_key.org
            return course_id[len('course-v1:'):].split('+')[0]
        except IndexError:
            return None

    def get_course_id(self, event):
        """Gets course_id from event's data."""

        # Get the event data:
        event_context = event.get('context')
        if event_context is None:
            # Assume it's old, and not worth logging...
            return None

        # Get the course_id from the data, and validate.
        course_id = self.normalize_course_id(event_context.get('course_id', ''))
        if course_id:
            if self.is_valid_course_id(course_id):
                return course_id
            else:
                return None
        return None

    def is_valid_course_id(self, course_id):
        """
        Determines if a course_id from an event log is possibly legitimate.
        """
        if course_id and course_id[-1] == '\n':
            return False
        return True

    def normalize_course_id(self, course_id):
        """Make a best effort to rescue malformed course_ids"""
        if course_id:
            return course_id.strip()
        else:
            return course_id

    def get_timestamp_from_datetime(self, dt):
        dt = dt.replace(tzinfo=pytz.utc)
        return int(time.mktime(dt.timetuple()))

    def get_event_time(self, event):
        """Returns a datetime object from an event object, if present."""
        try:
            return datetime.datetime.strptime(self.get_event_time_string(event), '%Y-%m-%dT%H:%M:%S.%f')
        except Exception:  # pylint: disable=broad-except
            return None

    def get_event_data(self, event_data):
        event_value = event_data.get('event')
        if event_value is None:
            return None

        if event_value == '':
            return {}

        if isinstance(event_value, str):
            try:
                return json.loads(event_value)
            except ValueError:
                return None

        return event_value

    def get_event_time_string(self, event):
        """Returns the time of the event as an ISO8601 formatted string."""
        try:
            # Get entry, and strip off time zone information.  Keep microseconds, if any.
            raw_timestamp = event['time']
            timestamp = raw_timestamp.split('+')[0]
            if '.' not in timestamp:
                timestamp = '{datetime}.000000'.format(datetime=timestamp)
            return timestamp
        except Exception:  # pylint: disable=broad-except
            return None

    def parse(self, event_data):
        raise NotImplementedError()

    def get_category(self, event):
        raise NotImplementedError()

    def is_ora_block(self, event, *args, **kwargs):
        raise NotImplementedError()

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_possible_points(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_problem_id(self, event, *args, **kwargs):
        raise NotImplementedError()

    def custom_event_condition(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_correctness(self, event_data, *args, **kwargs):
        raise NotImplementedError()

    def get_grade(self, correctness, *args, **kwargs):
        raise NotImplementedError()

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        raise NotImplementedError()

    def get_question_text(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_question_text_hash(self, question_text=None):
        return hashlib.md5(question_text.encode('utf-8')).hexdigest()

    def get_question_hash(self, display_name, question_text):
        return hashlib.md5(u''.join([display_name, question_text]).encode('utf-8')).hexdigest()

    def get_display_name(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_student_id(self, event, *args, **kwargs):
        raise NotImplementedError()

    def is_new_attempt(self, event, *args, **kwargs):
        raise NotImplementedError()

    def is_block_view(self, event, *args, **kwargs):
        raise NotImplementedError()


class ImageExplorerParser(EventParser):
    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.image_explorer

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        answers = event.get('event', {}).get('opened_hotspots', [])
        return '; '.join(answers)

    def get_correctness(self, event_data, *args, **kwargs):
        grade = event_data.get('grade', 0)
        max_grade = event_data.get('max_grade', 0)
        correctness = 'incorrect'
        if 0 < grade < max_grade:
            correctness = 'partially-correct'
        elif grade == max_grade:
            correctness = 'correct'

        return CorrectData(
            True,
            float(event_data.get('grade', 0)),
            float(event_data.get('max_grade', 0)),
            correctness
        )

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_grade(self, correctness, *args, **kwargs):
        if correctness.max_grade != 0:
            grade = correctness.earned_grade / correctness.max_grade
        else:
            grade = 0
        return grade

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_question_text(self, event, *args, **kwargs):
        return ""

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_block_view(self, event, *args, **kwargs):
        return False

    def is_new_attempt(self, event, *args, **kwargs):
        first_open = int(event.get('event', {}).get('first_open', False))
        return first_open


class ProblemParser(EventParser):

    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.problem

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event['event'].get('problem_id')

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_correctness(self, event_data, *args, **kwargs):
        return CorrectData(
            event_data['success'] == 'correct',
            float(event_data.get('grade', 0)),
            float(event_data.get('max_grade', 0)),
            event_data['success']
        )

    def get_grade(self, correctness, *args, **kwargs):
        if correctness.max_grade != 0:
            grade = correctness.earned_grade / correctness.max_grade
        else:
            grade = 1 if correctness.is_correct else 0
        return grade

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        answer_display = []
        event_data = event['event']
        submissions = event_data.get('submission', {})
        allowed_input_types = ['choicegroup', 'checkboxgroup', 'textline', 'formulaequationinput', 'optioninput']
        for answer_id, submission in submissions.items():
            if submission['input_type'] and submission['input_type'] in allowed_input_types:
                answers_text = submission['answer'] if isinstance(submission['answer'], list) else [
                    submission['answer']]
                processed_answers = []
                for item in answers_text:
                    processed_answers.append(re.sub(r'<choicehint\s*(selected=\"true\")*>.*?</choicehint>', '',
                                                    item.replace("\n", "").replace("\t", "").replace("\r", "")))
                answer_display.append(', '.join(processed_answers))
        return '; '.join(answer_display)

    def get_question_text(self, event, *args, **kwargs):
        event_data = event['event']
        question_text = ''
        submissions = event_data.get('submission', {})
        if submissions:
            for _, submission in submissions.items():
                if submission:
                    q_text = submission.get('question', '')
                    if question_text:
                        question_text = question_text + "; " + q_text
                    else:
                        question_text = q_text
        return question_text

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        attempts = int(event.get('event', {}).get('attempts', 1))
        return attempts == 1

    def is_block_view(self, event, *args, **kwargs):
        return False


class OraParser(EventParser):

    def parse(self, event_data):
        items = []
        parts = event_data.get('event', {}).get('parts', [])
        for part in parts:
            criterion_name = part.get('criterion', {}).get('name', None)
            if criterion_name:
                criterion_name = criterion_name.replace(":", " ")
                item = self.process(event_data, answer=part, criterion_name=criterion_name)
                if item:
                    items.append(item)
        return items

    def get_category(self, event):
        return EventCategory.ora

    def is_ora_block(self, event, *args, **kwargs):
        return True

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_possible_points(self, event, *args, **kwargs):
        answer = kwargs['answer']
        return int(answer.get('criterion', {}).get('points_possible', 0))

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_correctness(self, event_data, *args, **kwargs):
        answer = kwargs['answer']
        points_possible = int(answer.get('criterion', {}).get('points_possible', 0))
        points = int(answer.get('option', {}).get('points', 0))

        return CorrectData(
            points == points_possible,
            float(points),
            float(points_possible),
            None
        )

    def get_grade(self, correctness, *args, **kwargs):
        if correctness.max_grade != 0:
            grade = correctness.earned_grade / correctness.max_grade
        else:
            grade = 0
        return grade

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        answer = kwargs['answer']
        answer_display = answer.get('option', {}).get('name', '')
        return answer_display

    def get_question_text(self, event, *args, **kwargs):
        question_text = ''
        prompts_list = []
        prompts = event.get('event', {}).get('prompts', [])
        if prompts:
            for prompt in prompts:
                if 'description' in prompt:
                    prompts_list.append(prompt['description'])

        if prompts_list:
            question_text = u". ".join(prompts_list)
        return question_text.replace("\n", " ").replace("\t", " ").replace("\r", "")

    def get_display_name(self, event, *args, **kwargs):
        criterion_name = kwargs['criterion_name']
        return event.get('context').get('module', {}).get('display_name', '') + ': ' + criterion_name

    def get_saved_tags(self, event, **kwargs):
        criterion_name = kwargs['criterion_name']
        saved_tags = event.get('context').get('asides', {}).get('tagging_ora_aside', {}).get('saved_tags', {})
        return saved_tags.get(criterion_name, {})

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('asides', {}).get('student_properties_aside', {}).get('student_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return True

    def is_block_view(self, event, *args, **kwargs):
        return False


class OraWithoutCriteriaParser(EventParser):

    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.ora_empty_rubrics

    def is_ora_block(self, event, *args, **kwargs):
        return True

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return True

    def custom_event_condition(self, event, *args, **kwargs):
        rubric_count = int(event.get('event').get('rubric_count', 0))
        return rubric_count == 0

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_correctness(self, event_data, *args, **kwargs):
        return CorrectData(True, 1, 0, 'correct')

    def get_grade(self, correctness, *args, **kwargs):
        return 1

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        answers_parts = event.get('event').get('answer', {}).get('parts')
        if answers_parts is None:
            return ''

        answer = ' '.join([i.get('text', '') for i in answers_parts])
        return answer

    def get_question_text(self, event, *args, **kwargs):
        question_text = ''
        prompts_list = []
        prompts = event.get('event', {}).get('prompts', [])
        if prompts:
            for prompt in prompts:
                if 'description' in prompt:
                    prompts_list.append(prompt['description'])

        if prompts_list:
            question_text = u". ".join(prompts_list)
        return question_text.replace("\n", " ").replace("\t", " ").replace("\r", "")

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return True

    def is_block_view(self, event, *args, **kwargs):
        return False


class DndParser(EventParser):

    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.dnd

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_correctness(self, event_data, *args, **kwargs):
        correct = 0
        earned_grade = float(event_data.get('earned_score', 0))
        max_grade = float(event_data.get('max_score', 0))

        correctness = 'incorrect'
        if 0 < earned_grade < max_grade:
            correct = 1
            correctness = 'partially-correct'
        elif earned_grade == max_grade:
            correct = 1
            correctness = 'correct'
        return CorrectData(correct, earned_grade, max_grade, correctness)

    def get_grade(self, correctness, *args, **kwargs):
        if correctness.max_grade != 0:
            grade = correctness.earned_grade / correctness.max_grade
        else:
            grade = 1 if correctness.is_correct else 0
        return grade

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        event_data = event.get('event', {})
        items_state = {}
        for st in event_data.get('item_state'):
            zone_title = st.get('zone', {}).get('title', '')
            if zone_title:
                items_state[zone_title] = {
                    'display_name': st.get('display_name', ''),
                    'id': str(st.get('id', '0'))
                }

        answer_display_list = []
        answer_value_list = []
        zones = [z['title'] for z in event_data.get('zones', []) if 'title' in z]
        for zone_title in zones:
            item_state = items_state.get(zone_title)
            answer_display_list.append(item_state['display_name'] if item_state else '-Empty-')
            answer_value_list.append(item_state['id'] if item_state else '-1')

        correctness_title = 'incorrect'
        if 0 < correctness.earned_grade < correctness.max_grade:
            correctness_title = 'partially-correct'
        elif correctness.earned_grade == correctness.max_grade:
            correctness_title = 'correct'

        answer_data = {
            'answer_value': '|'.join(answer_value_list),
            'answer_display': '; '.join(answer_display_list),
            'correct': 1 if correctness.is_correct else 0,
            'correctness': correctness_title,
            'timestamp': timestamp,
            'attempts': event_data.get('attempts', 1),
        }
        return answer_data['answer_display']

    def get_question_text(self, event, *args, **kwargs):
        return ''

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return True

    def is_block_view(self, event, *args, **kwargs):
        return False


class ViewedParser(EventParser):

    def _is_ora(self, event):
        category = event.get('event', {}).get('category')
        return category == 'openassessment'

    def parse(self, event_data):
        if self._is_ora(event_data):
            items = []
            rubrics = event_data.get('event', {}).get('rubrics', [])
            if rubrics:
                for part in rubrics:
                    criterion_name = part.get('label', None)
                    if criterion_name:
                        criterion_name = criterion_name.replace(":", " ")
                        item = self.process(event_data, rubric=part, criterion_name=criterion_name)
                        items.append(item)
                return items
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.viewed

    def is_ora_block(self, event, *args, **kwargs):
        return self._is_ora(event)

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        if self._is_ora(event):
            rubrics = event.get('event', {}).get('rubrics', [])
            if not rubrics:
                return True
        return False

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_possible_points(self, event, *args, **kwargs):
        rubric = kwargs.get('rubric')
        if self._is_ora(event) and rubric:
            return max([x['points'] for x in rubric['options']])
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('event').get('usage_key')

    def get_correctness(self, event_data, *args, **kwargs):
        return CorrectData(False, 0, 1, None)

    def get_grade(self, correctness, *args, **kwargs):
        return 0

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        return 'No answer'

    def get_question_text(self, event, *args, **kwargs):
        return event.get('event').get('question_text', '').replace("\n", " ").replace("\t", " ").replace("\r", "")

    def get_display_name(self, event, *args, **kwargs):
        display_name = event.get('event').get('display_name', '')
        criterion_name = kwargs.get('criterion_name')
        if self._is_ora(event) and criterion_name:
            return display_name + ': ' + criterion_name
        return display_name

    def get_saved_tags(self, event, **kwargs):
        saved_tags = event.get('event').get('tagging_aside', {})
        return saved_tags

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return False

    def is_block_view(self, event, *args, **kwargs):
        return True

    def get_student_properites(self, event):
        result = {}
        tmp = event.get('event').get('student_properties_aside', {}).get('student_properties', {})
        types = ['registration', 'enrollment']
        for tp in types:
            result.update(tmp.get(tp, {}))
        return result


def parse_course_id(course_id):
    return list(course_id[len('course-v1:'):].split('+') + ([None] * 3))[:3]


def get_student_properites(properties):
    result = {}
    types = ['registration', 'enrollment']
    for tp in types:
        result.update(properties.get(tp, {}))
    return result
