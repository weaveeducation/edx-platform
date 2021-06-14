/**
 * The CopyXblockModal to copy XBlocks in course.
 */
define([
  'jquery',
  'backbone',
  'underscore',
  'gettext',
  'js/views/modals/base_modal',
  'jquery.multiselect'
],
function($, Backbone, _, gettext, BaseModal) {
  'use strict';
  
  var CopyToOtherCourseXBlockModal = BaseModal.extend({
    events : _.extend({}, BaseModal.prototype.events, {
        'click .action-save': 'save',
        'click .action-copy': 'save',
        keydown: 'keyHandler'
    }),
  
    options: $.extend({}, BaseModal.prototype.options, {
        modalSize: 'lg',
        selectedXblocks: []
    }),
  
    initialize: function() {
        BaseModal.prototype.initialize.call(this);
        this.template = this.loadTemplate('course-outline-modal');
        this.options.title = this.getTitle();
        this.progress = false;
        this.taskId = null;
        this.intervalId = null;
        this.done = false;
    },

    afterRender: function() {
        BaseModal.prototype.afterRender.call(this);
        this.initializeEditors();
    },
  
    getTitle: function () {
        return interpolate(
            gettext('Copy %(count)s components to other libraries'),
            { count: this.options.selectedXblocks.length }, true
        );
    },
  
    addActionButtons: function() {
        this.addActionButton('copy', gettext('Copy'), true);
        this.addActionButton('cancel', gettext('Cancel'));
    },
  
    getIntroductionMessage: function () {
        return interpolate(
            gettext('Please choose libraries where to copy %(count)s components'),
            { count: this.options.selectedXblocks.length }, true
        );
    },
  
    initializeEditors: function () {
        var self = this;
  
        $.ajax({
            url: '/libraries_listing',
            type: 'GET',
            dataType: 'json',
            success: function(data) {
                var windowTemplate = self.loadTemplate('copy-to-libraries');
                data.sort(function(a, b) {
                    if (a.display_name < b.display_name) return -1;
                    if (a.display_name > b.display_name) return 1;
                    return 0;
                });
                var result = [];
                $.each(data, function(index, library) {
                    // Exclude source library
                    if (library.location !== self.model.id) {
                        result.push({
                            id: library.location,
                            name: library.display_name + ' [ ' + library.org + ' / ' + library.course + ' ]'
                        });
                    }
                });
  
                self.$('.modal-section').html(windowTemplate({libraries: result}));
                self.$('.modal-section').find('select[name="copy-to-libraries"]').multiselect({
                    columns: 1,
                    search: true,
                    selectAll: true,
                    texts: {
                        placeholder: 'Select Libraries',
                        search: 'Search...'
                    }
                });
            },
            error: function(jqXHR, textStatus, errorThrown) {
                self.$('.modal-section').html(gettext('Library list can\'t be loaded from server'));
            }
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
  
    getRequestData: function () {
        var requestData = {
            'usage_keys': this.options.selectedXblocks,
            'copy_to_libraries': this.$('.modal-section').find('select[name="copy-to-libraries"]').val()
        };
        return $.extend.apply(this, [true, {}].concat(requestData));
    },

    keyHandler: function(event) {
        if (event.which === 27) {  // escape key
            this.hide();
        }
    },
  
    save: function(event) {
        event.preventDefault();
        if (this.progress) {
            return;
        }
        if (this.done) {
            this.hide();
            return;
        }
        var requestData = this.getRequestData();
        if (requestData.copy_to_libraries.length === 0) {
            return;
        }
        this.startCopy(requestData);
    },
  
    startCopy: function(data) {
        var self = this;
        this.getActionButton('copy').html('Please wait...');
        this.progress = true;
        this.$('.modal-section').find('.copy-to-libraries-result').html('');
        $.ajax({
            url: '/copy_components_to_libraries',
            type: 'POST',
            data: JSON.stringify(data),
            contentType: 'application/json',
            dataType: 'json',
            success: function(data) {
                if (data.task_id) {
                    self.taskId = data.task_id;
                    self.intervalId = setInterval(function() { self.checkCopy(); }, 5000);
                } else {
                    self.$('.modal-section').find('.copy-to-libraries-result').html(gettext("Error!"));
                    self.progress = false;
                    self.getActionButton('copy').html('Copy');
                }
            },
            error: function(jqXHR, textStatus, errorThrown) {
                self.$('.modal-section').find('.copy-to-libraries-result').html(gettext("Error!"));
                self.progress = false;
                self.getActionButton('copy').html('Copy');
            }
        });
    },
  
    checkCopy: function() {
        var self = this;
        $.ajax({
            url: '/copy_components_to_libraries_result',
            type: 'POST',
            data: JSON.stringify({'task_id': self.taskId}),
            contentType: 'application/json',
            dataType: 'json',
            success: function(data) {
                var html = '';
                if (data.result) {
                    html = '<div><strong>Done!</strong></div>';
                    clearInterval(self.intervalId);
                    self.progress = false;
                    self.done = true;
                    self.getActionButton('copy').html('Close');
                }
  
                $.each(data.libraries, function(index, library) {
                    var st = '<span>Not started</span>';
                    if (library.status === 'started') {
                        st = '<span>In progress</span>';
                    } else if (library.status === 'finished') {
                        st = '<span style="color: green;">Success</span>';
                    } else if (library.status === 'error') {
                        st = '<span style="color: red;">Fail</span>';
                    }
                    html = html + '<div>' + library.title + ': ' + st + '</div>';
                });
                self.$('.modal-section').find('.copy-to-libraries-result').html(html);
            }
        });
    }
  });
  
  return CopyToOtherCourseXBlockModal;
});
