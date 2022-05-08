from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData, ora_is_graded


class OraSubmissionParser(AbstractEventParser):

    def parse(self, event_data):
        items = []
        if self.is_ora_empty_rubrics(event_data):
            item = self.process(event_data)
            items.append(item)
        else:
            rubrics = event_data.get('event', {}).get('rubrics', [])
            if rubrics:
                for part in rubrics:
                    criterion_name = part.get('label', None)
                    if criterion_name:
                        criterion_name = criterion_name.replace(":", " ")
                        item = self.process(event_data, answer=part, criterion_name=criterion_name)
                        items.append(item)
        return items

    def get_category(self, event):
        if self.is_ora_empty_rubrics(event):
            return EventCategory.ora_empty_rubrics
        return EventCategory.ora

    def is_ora_block(self, event, *args, **kwargs):
        return True

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        event_data = event.get('event', {})
        if 'rubric_count' not in event_data:
            return False
        rubric_count = event_data.get('rubric_count')
        return rubric_count == 0

    def get_ora_status(self, event, *args, **kwargs):
        if not self.is_ora_empty_rubrics(event):
            return 'submitted'
        return None

    def custom_event_condition(self, event, *args, **kwargs):
        return True

    def get_possible_points(self, event, *args, **kwargs):
        if not self.is_ora_empty_rubrics(event):
            answer = kwargs['answer']
            return int(answer.get('criterion', {}).get('points_possible', 0))
        return None

    def get_problem_id(self, event, *args, **kwargs):
        return event.get('context').get('module', {}).get('usage_key')

    def get_correctness(self, event_data, *args, **kwargs):
        criterion_name = kwargs.get('criterion_name')
        if criterion_name:
            answer = kwargs['answer']
            points_possible = int(answer.get('criterion', {}).get('points_possible', 0))
            return CorrectData(False, 0, float(points_possible), None)
        return CorrectData(True, 1, 1, 'correct')

    def get_grade(self, correctness, *args, **kwargs):
        # correctness.earned_grade == 1 - in case of ORA without rubrics
        # correctness.earned_grade == 0 - in case of ORA with rubrics
        return correctness.earned_grade

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
