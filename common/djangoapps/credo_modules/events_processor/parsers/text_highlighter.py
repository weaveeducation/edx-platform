from django.utils.html import strip_tags
from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData


class TextHighlighterParser(AbstractEventParser):
    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.text_highlighter

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_ora_status(self, event, *args, **kwargs):
        return None

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        answers = event.get('event', {}).get('user_answers', [])
        return '; '.join(sorted(answers))

    def get_correctness(self, event_data, *args, **kwargs):
        grade = event_data.get('percent_completion', 0)
        max_grade = event_data.get('max_grade', 0)
        correctness = 'incorrect'
        if 0 < grade < max_grade:
            correctness = 'partially-correct'
        elif grade == max_grade:
            correctness = 'correct'

        return CorrectData(
            correctness != 'incorrect',
            float(grade),
            float(max_grade),
            correctness
        )

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_question_name(self, event, *args, **kwargs):
        return self.get_display_name(event, *args, **kwargs)

    def get_grade(self, correctness, *args, **kwargs):
        return correctness.earned_grade

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_question_text(self, event, *args, **kwargs):
        res_text = ''
        description = strip_tags(event.get('event', {}).get('description', '').replace("\n", " ").strip())
        text = strip_tags(event.get('event', {}).get('text', '').replace("\n", " ").strip())

        if description:
            res_text = description
        if text:
            if res_text:
                if res_text.endswith(('.', ';', ',')):
                    res_text = ' ' + text
                else:
                    res_text = '. ' + text
            else:
                res_text = text
        return res_text

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_block_view(self, event, *args, **kwargs):
        return False

    def is_new_attempt(self, event, *args, **kwargs):
        new_attempt = int(event.get('event', {}).get('new_attempt', False))
        return new_attempt
