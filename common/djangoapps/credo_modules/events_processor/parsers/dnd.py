from .abstract import AbstractEventParser
from ..utils import EventCategory, CorrectData


class DndParser(AbstractEventParser):

    def parse(self, event_data):
        item = self.process(event_data)
        return [item] if item else []

    def get_category(self, event):
        return EventCategory.dnd

    def is_ora_block(self, event, *args, **kwargs):
        return False

    def is_ora_empty_rubrics(self, event, *args, **kwargs):
        return False

    def get_ora_status(self, event, *args, **kwargs):
        return None

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

    def get_question_name(self, event, *args, **kwargs):
        return self.get_display_name(event, *args, **kwargs)

    def get_student_id(self, event, *args, **kwargs):
        return event.get('context').get('user_id', None)

    def is_new_attempt(self, event, *args, **kwargs):
        return True

    def is_block_view(self, event, *args, **kwargs):
        return False
