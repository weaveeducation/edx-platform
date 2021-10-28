from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData, ora_is_graded


class OraWithoutCriteriaParser(AbstractEventParser):

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
        event_data = event.get('event', {})
        if 'rubric_count' not in event_data:
            return False
        rubric_count = event_data.get('rubric_count')
        return rubric_count == 0

    def get_possible_points(self, event, *args, **kwargs):
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_correctness(self, event_data, *args, **kwargs):
        return CorrectData(True, 1, 1, 'correct')

    def get_grade(self, correctness, *args, **kwargs):
        return 1

    def get_answers(self, event, correctness, timestamp, *args, **kwargs):
        return 'n/a'

    def get_ora_user_answer(self, event):
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
            question_text = ". ".join(prompts_list)
        return question_text.replace("\n", " ").replace("\t", " ").replace("\r", "").replace("|", " ")

    def get_display_name(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('display_name', '')

    def get_question_name(self, event, *args, **kwargs):
        return self.get_display_name(event, *args, **kwargs)

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return True

    def is_block_view(self, event, *args, **kwargs):
        return False

    def get_graded(self, event, *args, **kwargs):
        return ora_is_graded(event)
