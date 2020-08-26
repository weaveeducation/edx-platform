/* globals _ */

(function(_) {
    'use strict';

    var CredoInsightsConstructor = (function() {
        function CredoInsightsConstructorBlock($section) {
            this.$section = $section;
            this.$section.data('wrapper', this);
            this.initialized = false;
        }

        CredoInsightsConstructorBlock.prototype.onClickTitle = function() {
            var block = this.$section.find('.credo-insights');
            if (!this.initialized) {
                this.initialized = true;
            }
        };

        return CredoInsightsConstructorBlock;
    }());

    _.defaults(window, {
        InstructorDashboard: {}
    });

    _.defaults(window.InstructorDashboard, {
        sections: {}
    });

    _.defaults(window.InstructorDashboard.sections, {
        CredoInsightsConstructor: CredoInsightsConstructor
    });

    this.CredoInsightsConstructor = CredoInsightsConstructor;
}).call(this, _);
