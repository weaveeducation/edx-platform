/**
 * The CopyXblockModal to copy XBlocks in course.
 */
define([
    'jquery',
    'backbone',
    'underscore',
    'gettext',
    'js/views/modals/base_modal',
    'edx-ui-toolkit/js/utils/string-utils',
    'jquery.multiselect'
],
function($, Backbone, _, gettext, BaseModal, StringUtils) {
    'use strict';

    var CopyToOtherCourseXBlockModal = BaseModal.extend({
        events: _.extend({}, BaseModal.prototype.events, {
            'click .action-publish': 'publish',
            keydown: 'keyHandler'
        }),

        options: $.extend({}, BaseModal.prototype.options, {
            modalSize: 'med'
        }),

        initialize: function() {
            BaseModal.prototype.initialize.call(this);
            this.template = this.loadTemplate('course-outline-modal');
            this.options.title = this.getTitle();
            this.progress = false;
            this.taskId = null;
            this.intervalId = null;
            this.done = false;
            this.siblings = [];
        },

        afterRender: function() {
            BaseModal.prototype.afterRender.call(this);
            this.initializeEditors();
        },

        getTitle: function() {
            return StringUtils.interpolate(
                gettext('Publish {display_name}'),
                {display_name: this.model.get('display_name')}
            );
        },

        getIntroductionMessage: function() {
            return StringUtils.interpolate(
                gettext('Publish all unpublished changes for this {type}?'),
                {type: this.options.xblockType}
            );
        },

        addActionButtons: function() {
            this.addActionButton('publish', gettext('Publish'), true);
            this.addActionButton('cancel', gettext('Cancel'));
        },

        initializeEditors: function() {
            var parrentElement = this.$('.modal-section');
            var publishChangesTemplate = this.loadTemplate('publish-editor');
            var pushChangesTemplate = this.loadTemplate('push-changes-to-siblings');
            parrentElement.append(publishChangesTemplate({xblockInfo: this.model}))
            parrentElement.append(pushChangesTemplate({siblings: this.siblings}))
        },

        requestCoursesWithDuplicates: function() {
            var self = this;
            return $.ajax({
                url: '/get_courses_with_duplicates/' + self.model.id,
                type: 'GET',
                success: function(response) {
                    self.siblings = response.data
                }
            }).then(function() {
                return self.siblings
            });
        },

        getContentHtml: function() {
            return this.template(this.getContext());
        },

        getContext: function() {
            return $.extend({
                xblockInfo: this.model,
                introductionMessage: this.getIntroductionMessage(),
                enable_proctored_exams: this.options.enable_proctored_exams,
                enable_timed_exams: this.options.enable_timed_exams
            });
        },

        getRequestData: function() {
            var self = this;
            var requestData = {
                publish: 'make_public',
                related_courses: {}
            };
            this.$('.modal-section').find('select[name="change-type"]').each(function() {
                const el = self.$(this)
                requestData.related_courses[el.data('id')] = el.val()
            });
            return requestData;
        },

        keyHandler: function(event) {
            if (event.which === 27) {  // escape key
                this.hide();
            }
        },

        publish: function(event) {
            event.preventDefault();
            if (this.progress) {
                return;
            }
            if (this.done) {
                this.hide();
                return;
            }
            var requestData = this.getRequestData();
            this.startCopy(requestData);
        },

        startCopy: function(data) {
            var self = this;
            var modalEl = this.$('.modal-section')
            this.progress = true;
            this.getActionButton('publish').html('Please wait...');
            modalEl.find('select[name="change-type"]').prop('disabled', true);
            modalEl.find('.push-changes-to-siblings-result').html('');
            this.model.save(data, {
                patch: true,
                success: function(data) {
                    if (self.options.onSave) {
                        self.options.onSave()
                    }
                    if (data.get('update_related_courses_task_id')) {
                        self.taskId = data.get('update_related_courses_task_id');
                        self.intervalId = setInterval(function() { self.checkCopy(); }, 1000);
                    } else {
                        self.progress = false;
                        self.hide()
                    }
                },
                error: function(jqXHR, textStatus, errorThrown) {
                    modalEl.find('.push-changes-to-siblings-result').html(gettext('Error!'));
                    self.progress = false;
                    self.getActionButton('publish').html('Publish');
                }
            });
        },

        checkCopy: function() {
            var self = this;
            var modalEl = this.$('.modal-section')
            $.ajax({
                url: '/update_block_in_related_courses_result',
                type: 'POST',
                data: JSON.stringify({task_id: self.taskId}),
                contentType: 'application/json',
                dataType: 'json',
                success: function(data) {
                    if (data.result) {
                        clearInterval(self.intervalId);
                        self.progress = false;
                        self.done = true;
                        var html = '<div><strong>Done!</strong></div>';
                        modalEl.find('.push-changes-to-siblings-result').html(html);
                        self.getActionButton('publish').html('Close');
                    }

                    $.each(data.courses, function(index, item) {
                        var status = '(Not started)';
                        var color = 'gray'
                        if (item.status === 'started') {
                            status = '(In progress)';
                        } else if (item.status === 'finished') {
                            status = '(Success)';
                            color = 'green'
                        } else if (item.status === 'error') {
                            status = '(Fail)';
                            color = 'red'
                        }
                        modalEl.find('*[data-id="' + item.title + '"] .status')
                            .html(status).css('color', color);
                    });
                }
            });
        }
    });

    return CopyToOtherCourseXBlockModal;
});
