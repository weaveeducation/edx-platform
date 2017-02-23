/* globals _ */

(function(Backbone, $, _, gettext) {
    'use strict';

    if (typeof window.setup_debug === 'undefined') {
        window.setup_debug = function(element_id, edit_link, staff_context) {
            // stub function
        }
    }

    var OpenResponseAssessment = (function() {
        function OpenResponseAssessment($section) {
            var self = this;

            this.$section = $section;
            this.$section.data('wrapper', this);

            $section.find(".open-response-assessment-content").hide();
            $section.find('.open-response-assessment-item').hide();
            $section.find('.open-response-assessment-msg').show();

            var AssessmentCell = Backgrid.UriCell.extend({
                staff: false,
                render: function () {
                    this.$el.empty();
                    var url = this.model.get('url');
                    var rawValue = this.model.get(this.column.get("name"));
                    var staffAssessment = this.model.get('staff_assessment');
                    var formattedValue = this.formatter.fromRaw(rawValue, this.model);
                    var link = null;
                    if (!this.staff || (this.staff && staffAssessment)) {
                        link = $("<a>", {
                            text: formattedValue,
                            title: this.title || formattedValue
                        });
                        this.$el.append(link);
                        link.on("click", $.proxy(self, "displayOraBlock", url, this.staff));
                    } else {
                        this.$el.append(formattedValue);
                    }
                    this.delegateEvents();
                    return this;
                }
            });

            var StaffCell = AssessmentCell.extend({
                staff: true
            });

            this._columns = [
                {name: 'parent_name', label: gettext("Parent Section"), label_summary: gettext("Parent Sections"),
                    cell: "string", num: false, editable: false},
                {name: 'name', label: gettext("Assessment"), label_summary: gettext("Assessments"),
                    cell: AssessmentCell, num: false, editable: false
                },
                {name: 'total', label: gettext("Total Responses"), label_summary: gettext("Total Responses"),
                    cell: "string", num: true, editable: false},
                {name: 'training', label: gettext("Training"), label_summary: gettext("Training"),
                    cell: "string", num: true, editable: false},
                {name: 'peer', label: gettext("Peer"), label_summary: gettext("Peer"),
                    cell: "string", num: true, editable: false},
                {name: 'self', label: gettext("Self"), label_summary: gettext("Self"),
                    cell: "string", num: true, editable: false},
                {name: 'staff', label: gettext("Staff"), label_summary: gettext("Staff"),
                    cell: StaffCell, num: true, editable: false},
                {name: 'done', label: gettext("Final Grade Received"), label_summary: gettext("Final Grade Received"),
                    cell: "string", num: true, editable: false}
            ];
        }

        OpenResponseAssessment.prototype.refreshGrids = function(force) {
            force = force || false;

            var self = this;
            var $section = this.$section;
            var block = $section.find('.open-response-assessment-block');
            var dataUrl = block.data('endpoint');
            var dataRendered = parseInt(block.data('rendered'));

            if (!dataRendered || force) {
                $.ajax({
                    type: 'GET',
                    dataType: 'json',
                    url: dataUrl,
                    success: function(data) {
                        block.data('rendered', 1);
                        $section.find('.open-response-assessment-msg').hide();
                        self.showSummaryGrid(data);
                        self.showOpenResponsesGrid(data);
                    },
                    error: function(err) {
                        $section.find('.open-response-assessment-msg')
                            .text(gettext('List of Open Assessments is unavailable'));
                    }
                });
            }
        };

        OpenResponseAssessment.prototype.onClickTitle = function() {
            this.refreshGrids();
        };

        OpenResponseAssessment.prototype.showSummaryGrid = function(data) {
            var $section = this.$section;
            var summaryData = [];
            var summaryDataMap = {};

            $section.find(".open-response-assessment-summary").empty();

            $.each(this._columns, function(index, v) {
                summaryData.push({
                    title: v['label_summary'],
                    value: 0,
                    num: v['num'],
                    class: v['name']
                });
                summaryDataMap[v['name']] = index;

            });

            $.each(data, function(index, obj) {
                $.each(obj, function(key, value) {
                    var idx = 0;
                    if (key in summaryDataMap) {
                        idx = summaryDataMap[key];
                        if (summaryData[idx]['num']) {
                            summaryData[idx]['value'] += value;
                        } else {
                            summaryData[idx]['value'] += 1;
                        }
                    }
                });
            });

            var templateData = _.template($('#open-response-assessment-summary-tpl').text());
            $section.find(".open-response-assessment-summary").append(templateData({
                oraSummary: summaryData
            }));
        };

        OpenResponseAssessment.prototype.showOpenResponsesGrid = function(data) {
            var $section = this.$section;
            $section.find('.open-response-assessment-content').show();
            var collection = new Backbone.Collection(data);

            $section.find(".open-response-assessment-main-table").empty();

            var grid = new Backgrid.Grid({
                columns: this._columns,
                collection: collection
            });

            $section.find(".open-response-assessment-main-table").append(grid.render().el);
        };

        OpenResponseAssessment.prototype.displayOraBlock = function(url, isStaff) {
            var $section = this.$section;
            var self = this;
            var data = {};

            if (isStaff) {
                data['is_staff'] = 1;
            }

            $section.find(".open-response-assessment-content").hide();
            $section.find('.open-response-assessment-msg').show();

            $.ajax({
                type: 'GET',
                dataType: 'json',
                data: data,
                url: url,
                success: function(data) {
                    var el = $section.find('.open-response-assessment-item');
                    var block = el.find('.open-response-assessment-item-block');
                    var fragment = new XBlockFragment();

                    $section.find('.open-response-assessment-msg').hide();
                    el.show();

                    self.renderBreadcrumbs();

                    var fragmentsRendered = fragment.render(data, block);
                    fragmentsRendered.done(function() {
                        XBlock.initializeBlock($(block).find('.xblock')[0]);
                    });
                }});
        };

        OpenResponseAssessment.prototype.renderBreadcrumbs = function() {
            var $section = this.$section;
            var breadcrumbs = $section.find(".open-response-assessment-item-breadcrumbs");
            var text = gettext('Back to Full List');
            var fullListItem = $("<a>", {
                html: '&larr;&nbsp;' + text,
                title: text
            });

            breadcrumbs.append(fullListItem);
            fullListItem.on("click", $.proxy(this, "backToOpenResponsesGrid"));
        };

        OpenResponseAssessment.prototype.backToOpenResponsesGrid = function() {
            var $section = this.$section;
            $section.find(".open-response-assessment-item-breadcrumbs").empty();
            $section.find(".open-response-assessment-item-block").empty();
            $section.find('.open-response-assessment-item').hide();
            $section.find('.open-response-assessment-msg').show();
            this.refreshGrids(true);
        };

        return OpenResponseAssessment;
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
}).call(this, Backbone, $, _, gettext);
