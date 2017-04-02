/* globals _ */

(function(_) {
    'use strict';

    if (typeof window.setup_debug === 'undefined') {
        window.setup_debug = function(element_id, edit_link, staff_context) {
            // stub function
        }
    }

    var OpenResponseAssessment = (function() {
        function OpenResponseAssessmentBlock($section) {
            this.$section = $section;
            this.$section.data('wrapper', this);
        }

        OpenResponseAssessmentBlock.prototype.onClickTitle = function() {
            var block = this.$section.find('.open-response-assessment');
            XBlock.initializeBlock($(block).find('.xblock')[0]);
        };

        return OpenResponseAssessmentBlock;
    }());

    _.defaults(window, {
        InstructorDashboard: {}
    });

    _.defaults(window.InstructorDashboard, {
        sections: {}
    });

    _.defaults(window.InstructorDashboard.sections, {
        OpenResponseAssessment: OpenResponseAssessment
    });

    this.OpenResponseAssessment = OpenResponseAssessment;
}).call(this, _);
