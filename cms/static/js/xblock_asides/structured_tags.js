(function($) {
    'use strict';
    var EditTagsModal = null;

    require(["jquery", "underscore", "gettext", "js/views/modals/base_modal", "common/js/components/utils/view_utils"],
        function ($, _, gettext, BaseModal, ViewUtils) {

        EditTagsModal = BaseModal.extend({
            events: {
                "click .action-save": "save"
            },

            initialize: function(options) {
                BaseModal.prototype.initialize.call(this, options);
                this.events = _.extend({}, BaseModal.prototype.events, this.events);
                this.html = '';
                this.initState = null;
                this.saveDisabled = true;
                this.tag_category = options.tag_category
            },

            setURLs: function(options) {
                this.urlEdit = options.urlEdit;
                this.urlSave = options.urlSave;
            },

            getContentHtml: function() {
                return this.html;
            },

            save: function(event) {
                var self = this;
                var postData = {};

                event.preventDefault();

                var tags_editor = $(self.$el).find('.tags_editor');
                var txtVal = $(tags_editor).val();
                if (txtVal != self.initState) {
                    postData[this.tag_category] = txtVal;
                }

                ViewUtils.runOperationShowingMessage(gettext('Saving'), function() {
                    return $.post(self.urlSave, postData);
                }).done(function() {
                    self.onSave();
                });
            },

            enableActionButton: function(type) {
                this.getActionBar().find('.action-' + type).prop('disabled', false).removeClass('is-disabled');
            },

            disableActionButton: function(type) {
                this.getActionBar().find('.action-' + type).prop('disabled', true).addClass('is-disabled');
            },

            onSave: function() {
                this.hide();
                location.reload();
            },

            edit: function() {
                var self = this;

                this.show();
                this.getActionBar().hide();


                $.get(this.urlEdit, { tag_category: this.tag_category }).done(function(data) {
                    self.html = data.html;
                    self.renderContents();
                    self.getActionBar().show();
                    self.disableActionButton('save');
                    self.saveDisabled = true;
                    self.resize();

                    var tags_editor = $(self.$el).find('.tags_editor');
                    self.initState = tags_editor.val();

                    $(tags_editor).bind('input propertychange', function() {
                        if (self.saveDisabled && ($(tags_editor).val() != self.initState)) {
                            self.saveDisabled = false;
                            self.enableActionButton('save');
                        }
                    });
                });
            }
        });
    });

    function StructuredTagsView(runtime, element) {

        var $element = $(element);

        $element.find("select").each(function() {
            var loader = this;
            var sts = $(this).attr('structured-tags-select-init');

            if (typeof sts === typeof undefined || sts === false) {
                $(this).attr('structured-tags-select-init', 1);
                $(this).change(function(e) {
                    e.preventDefault();
                    var selectedKey = $(loader).find('option:selected').val();
                    runtime.notify('save', {
                        state: 'start',
                        element: element,
                        message: gettext('Updating Tags')
                    });
                    $.post(runtime.handlerUrl(element, 'save_tags'), {
                        'tag': $(loader).attr('name') + ':' + selectedKey
                    }).done(function() {
                        runtime.notify('save', {
                            state: 'end',
                            element: element
                        });
                    });
                });
            }
        });

        $($element).find('.edit_tags').click(function(){
            if (EditTagsModal) {
                var editTagModal = new EditTagsModal({
                    modalName: 'edit-xblockaside-tags',
                    addSaveButton: true,
                    modalSize: 'med',
                    title: gettext("Editing Available Tag Values"),
                    tag_category: $(this).attr('tag_category')
                });
                editTagModal.setURLs({
                    urlEdit: runtime.handlerUrl(element, 'edit_tags_view'),
                    urlSave: runtime.handlerUrl(element, 'update_values')
                });
                editTagModal.edit();
            }
        });
    }

    function initializeStructuredTags(runtime, element) {
        return new StructuredTagsView(runtime, element);
    }

    window.StructuredTagsInit = initializeStructuredTags;
})($);
