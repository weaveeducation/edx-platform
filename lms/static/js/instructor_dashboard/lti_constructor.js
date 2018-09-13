/* globals _ */

(function(_) {
    'use strict';

    var LtiConstructor = (function() {
        function LtiConstructorBlock($section) {
            this.$section = $section;
            this.$section.data('wrapper', this);
            this.initialized = false;
        }

        LtiConstructorBlock.prototype.onClickTitle = function() {
            var block = this.$section.find('.lti-constructor');
            if (!this.initialized) {
                this.initialized = true;
            }
        };

        return LtiConstructorBlock;
    }());

    _.defaults(window, {
        InstructorDashboard: {}
    });

    _.defaults(window.InstructorDashboard, {
        sections: {}
    });

    _.defaults(window.InstructorDashboard.sections, {
        LtiConstructor: LtiConstructor
    });

    this.LtiConstructor = LtiConstructor;
}).call(this, _);
