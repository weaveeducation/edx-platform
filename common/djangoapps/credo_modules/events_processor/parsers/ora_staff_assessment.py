from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData, ora_is_graded


class OraStaffAssessmentParser(AbstractEventParser):

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

    def get_ora_status(self, event, *args, **kwargs):
        return 'staff_graded'

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

        correctness = 'incorrect'
        if 0 < points < points_possible:
            correctness = 'partially-correct'
        elif points == points_possible:
            correctness = 'correct'

        return CorrectData(
            points == points_possible,
            float(points),
            float(points_possible),
            correctness
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
        criterion_name = kwargs['criterion_name']
        return self.get_display_name(event, *args, **kwargs) + ': ' + criterion_name.strip()

    def get_saved_tags(self, event, **kwargs):
        criterion_name = kwargs['criterion_name']
        saved_tags = event.get('context').get('asides', {}).get('tagging_ora_aside', {}).get('saved_tags', {})
        return saved_tags.get(criterion_name.replace('_dot_', '.'), {})

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('asides', {}).get('student_properties_aside', {}).get('student_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return True

    def is_block_view(self, event, *args, **kwargs):
        return False

    def get_graded(self, event, *args, **kwargs):
        return ora_is_graded(event)
