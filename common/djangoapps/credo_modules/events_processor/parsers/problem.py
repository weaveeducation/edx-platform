import re
from collections import OrderedDict
from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData


class ProblemParser(AbstractEventParser):

    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.problem

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_ora_status(self, event, *args, **kwargs):
        return None

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
        allowed_input_types = ['choicegroup', 'checkboxgroup', 'textline', 'formulaequationinput', 'optioninput']

        submissions_raw = event_data.get('submission', {})
        submissions = OrderedDict()
        submissions_raw_keys = sorted(list(submissions_raw.keys()))
        for sk in submissions_raw_keys:
            submissions[sk] = submissions_raw[sk]

        for answer_id, submission in submissions.items():
            if submission['input_type'] and submission['input_type'] in allowed_input_types:
                answers_text = submission['answer'] if isinstance(submission['answer'], list) else [
                    submission['answer']]
                processed_answers = []
                for item in answers_text:
                    item_upd = item.replace("\n", "").replace("\t", "").replace("\r", "").replace("|", " ")
                    item_upd = re.sub(r'<choicehint\s*(selected=\"true\")*>.*?</choicehint>', '', item_upd)
                    item_upd = re.sub(r'<choicehint\s*(selected=\"false\")*>.*?</choicehint>', '', item_upd)
                    item_upd = item_upd.strip()
                    processed_answers.append(item_upd)

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

    def get_question_name(self, event, *args, **kwargs):
        return self.get_display_name(event, *args, **kwargs)

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        attempts = int(event.get('event', {}).get('attempts', 1))
        return attempts == 1

    def is_block_view(self, event, *args, **kwargs):
        return False
