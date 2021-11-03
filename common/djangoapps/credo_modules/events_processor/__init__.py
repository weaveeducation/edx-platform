from .parsers.problem import ProblemParser
from .parsers.dnd import DndParser
from .parsers.ora_without_criteria import OraWithoutCriteriaParser
from .parsers.ora import OraParser
from .parsers.viewed import ViewedParser
from .parsers.image_explorer import ImageExplorerParser
from .parsers.free_text_response import FreeTextResponseParser


class EventProcessor:

    @classmethod
    def process(cls, event_type, event_data):
        parser = {
            'problem_check': lambda: ProblemParser(),
            'edx.drag_and_drop_v2.item.dropped': lambda: DndParser(),
            'openassessmentblock.create_submission': lambda: OraWithoutCriteriaParser(),
            'openassessmentblock.staff_assess': lambda: OraParser(),
            'sequential_block.viewed': lambda: ViewedParser(),
            'sequential_block.remove_view': lambda: ViewedParser(),
            'xblock.image-explorer.hotspot.opened': lambda: ImageExplorerParser(),
            'xblock.freetextresponse.submit': lambda: FreeTextResponseParser()
        }.get(event_type, lambda: None)()

        print(f'>>>>>>>>>>>>>>>> ---------- {event_type} - {parser}')
        if not parser:
            return None

        return parser.parse(event_data)
