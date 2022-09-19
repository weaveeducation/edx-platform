from .parsers.problem import ProblemParser
from .parsers.dnd import DndParser
from .parsers.ora_submission import OraSubmissionParser
from .parsers.ora_staff_assessment import OraStaffAssessmentParser
from .parsers.viewed import ViewedParser
from .parsers.image_explorer import ImageExplorerParser
from .parsers.free_text_response import FreeTextResponseParser
from .parsers.text_highlighter import TextHighlighterParser


class EventProcessor:

    @classmethod
    def process(cls, event_type, event_data):
        parser = {
            'problem_check': lambda: ProblemParser(),
            'edx.drag_and_drop_v2.item.dropped': lambda: DndParser(),
            'openassessmentblock.create_submission': lambda: OraSubmissionParser(),
            'openassessmentblock.staff_assess': lambda: OraStaffAssessmentParser(),
            'sequential_block.viewed': lambda: ViewedParser(),
            'sequential_block.remove_view': lambda: ViewedParser(),
            'xblock.image-explorer.hotspot.opened': lambda: ImageExplorerParser(),
            'xblock.text-highlighter.new_submission': lambda: TextHighlighterParser(),
            'xblock.freetextresponse.submit': lambda: FreeTextResponseParser()
        }.get(event_type, lambda: None)()

        if not parser:
            return None

        return parser.parse(event_data)
