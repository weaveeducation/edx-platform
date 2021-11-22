import datetime
import hashlib
import json
from ..event_data import EventData
from ..utils import get_timestamp_from_datetime, update_course_and_student_properties,\
    get_prop_user_info, filter_properties, combine_student_properties


class AbstractEventParser:

    def _get_md5(self, val):
        return hashlib.md5(val.encode('utf-8')).hexdigest()

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
        dtime_ts = get_timestamp_from_datetime(dtime)

        course_id = self.get_course_id(event)
        user_id = self.user_info(event)
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
        question_name = self.get_question_name(event, *args, **kwargs)
        question_text = self.get_question_text(event, *args, **kwargs)
        question_text_hash = self.get_question_text_hash(question_text)
        student_properties = self.get_student_properties(event)
        term = dtime.strftime("%B %Y")
        course, student_properties = update_course_and_student_properties(course, student_properties)
        prop_user_email, prop_user_name = get_prop_user_info(student_properties)

        student_properties = filter_properties(student_properties)

        answers = self.get_answers(event, correct_data, dtime_ts, grade=grade, *args, **kwargs)
        criterion_name = kwargs.get('criterion_name', None)
        if criterion_name:
            criterion_name = criterion_name.strip()
            block_tag_id = self._get_md5(problem_id + '|' + criterion_name)
        else:
            block_tag_id = self._get_md5(problem_id)

        correctness = correct_data.correctness if correct_data else None
        is_correct = correct_data.is_correct

        answer_id = str(user_id) + '-' + problem_id
        is_ora_block = self.is_ora_block(event, *args, **kwargs)
        is_ora_empty_rubrics = self.is_ora_empty_rubrics(event, *args, **kwargs)
        ora_user_answer = self.get_ora_user_answer(event)
        ora_status = self.get_ora_status(event, *args, **kwargs)

        if is_ora_block and not is_ora_empty_rubrics:
            answer_id = answer_id + '-' + criterion_name
        answer_id = self._get_md5(answer_id)

        graded = self.get_graded(event, *args, **kwargs)

        return EventData(
            category=self.get_category(event),
            course_id=course_id,
            org_id=org_id,
            course=course,
            run=run,
            block_id=problem_id,
            block_tag_id=block_tag_id,
            timestamp=timestamp,
            dtime=dtime,
            dtime_ts=dtime_ts,
            saved_tags=saved_tags,
            student_properties=student_properties,
            grade=grade,
            max_grade=max_grade,
            user_id=user_id,
            display_name=display_name,
            question_name=question_name,
            question_text=question_text,
            question_text_hash=question_text_hash,
            answers=answers,
            is_ora_empty_rubrics=is_ora_empty_rubrics,
            is_block_view=self.is_block_view(event, *args, **kwargs),
            possible_points=self.get_possible_points(event, *args, **kwargs),
            ora_block=is_ora_block,
            ora_status=ora_status,
            is_new_attempt=self.is_new_attempt(event, *args, **kwargs),
            criterion_name=criterion_name,
            correctness=correctness,
            is_correct=is_correct,
            term=term,
            answer_id=answer_id,
            prop_user_name=prop_user_name,
            prop_user_email=prop_user_email,
            ora_user_answer=ora_user_answer,
            graded=graded
        )

    def user_info(self, event):
        user_id = self.get_student_id(event)
        return user_id

    def check_exclude_insights(self, user_id, course_id):
        pass

    def get_ora_user_answer(self, event):
        return None

    def convert_tags(self, saved_tags):
        tags_extended_lst = []
        for _, tag_val in saved_tags.items():
            tag_val_lst = [tag_val] if isinstance(tag_val, str) else tag_val
            for tag in tag_val_lst:
                tag_split_lst = tag.split(' - ')
                for idx, _ in enumerate(tag_split_lst):
                    tag_new_val = ' - '.join(tag_split_lst[0:idx + 1])
                    if tag_new_val not in tags_extended_lst:
                        tags_extended_lst.append(tag_new_val)
        return tags_extended_lst

    def get_student_properties(self, event):
        tmp = event.get('context').get('asides', {}).get('student_properties_aside', {}) \
            .get('student_properties', {})
        return combine_student_properties(tmp)

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

    def get_graded(self, event, *args, **kwargs):
        return None

    def parse(self, event_data):
        raise NotImplementedError()

    def get_category(self, event):
        raise NotImplementedError()

    def is_ora_block(self, event, *args, **kwargs):
        raise NotImplementedError()

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_ora_status(self, event, *args, **kwargs):
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

    def get_display_name(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_question_name(self, event, *args, **kwargs):
        raise NotImplementedError()

    def get_student_id(self, event, *args, **kwargs):
        raise NotImplementedError()

    def is_new_attempt(self, event, *args, **kwargs):
        raise NotImplementedError()

    def is_block_view(self, event, *args, **kwargs):
        raise NotImplementedError()
