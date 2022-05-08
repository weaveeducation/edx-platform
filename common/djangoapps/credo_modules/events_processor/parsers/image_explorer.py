from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData


class ImageExplorerParser(AbstractEventParser):
    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.image_explorer

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_ora_status(self, event, *args, **kwargs):
        return None

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

    def get_question_name(self, event, *args, **kwargs):
        return self.get_display_name(event, *args, **kwargs)

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
