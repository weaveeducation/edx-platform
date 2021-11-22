from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData


class FreeTextResponseParser(AbstractEventParser):

    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.freetextresponse

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_ora_status(self, event, *args, **kwargs):
        return None

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        return event.get('event', {}).get('answer', '')

    def get_correctness(self, event_data, *args, **kwargs):
        weight = event_data.get('weight', 0)
        grade = 1 if weight > 0 else 0
        max_grade = 1 if weight > 0 else 0
        return CorrectData(
            True,
            float(grade),
            float(max_grade),
            'correct'
        )

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_question_name(self, event, *args, **kwargs):
        return self.get_display_name(event, *args, **kwargs)

    def get_grade(self, correctness, *args, **kwargs):
        return correctness.max_grade

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_question_text(self, event, *args, **kwargs):
        return event.get('event', {}).get('prompt', '')

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_block_view(self, event, *args, **kwargs):
        return False

    def is_new_attempt(self, event, *args, **kwargs):
        attempt_num = int(event.get('event', {}).get('attempt_num', 1))
        return attempt_num == 1
