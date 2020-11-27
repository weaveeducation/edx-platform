(function($) {
    'use strict';
    var EditTagsModal = null;

    require(["jquery", "underscore", "gettext", "js/views/modals/base_modal", "common/js/components/utils/view_utils"],
        function ($, _, gettext, BaseModal, ViewUtils) {

        EditTagsModal = BaseModal.extend({
            events: _.extend({}, BaseModal.prototype.events, {
                "click .action-save": "save"
            }),

            options: $.extend({}, BaseModal.prototype.options, {
                modalName: 'edit-xblock',
                view: 'studio_view',
                viewSpecificClasses: 'modal-editor confirm',
                addPrimaryActionButton: true
            }),

            initialize: function(options) {
                BaseModal.prototype.initialize.call(this, options);
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
        var saveTagsInProgress = false;
        var tagSelectors = {};
        var studioRuntime = new window.StudioRuntime.v1();

        $element.find("input").each(function() {
            tagSelectors[$(this).attr('name')] = $(this).magicSuggest({
                data: $(this).data('values'),
                width: 700,
                value: $(this).data('current-values'),
                allowFreeEntries: false,
                disabled: $(this).is('[readonly]') ? true : false,
                maxSelection: 1000,
                inputCfg: {"aria-label": $(this).attr('name')}
            });
        });

        $($element).find('.save_tags').click(function(e){
            if (!saveTagsInProgress) {
                saveTagsInProgress = true;
                var dataToPost = {};

                $.each(tagSelectors, function(tagName, tagSelector) {
                    dataToPost[tagName] = tagSelector.getValue();
                });

                e.preventDefault();
                runtime.notify('save', {
                    state: 'start',
                    element: element,
                    message: gettext('Updating Tags')
                });

                $.post(studioRuntime.handlerUrl(element, 'save_tags'), dataToPost).done(function() {
                    saveTagsInProgress = false;
                    runtime.notify('save', {
                        state: 'end',
                        element: element
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
                    urlEdit: studioRuntime.handlerUrl(element, 'edit_tags_view'),
                    urlSave: studioRuntime.handlerUrl(element, 'update_values')
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
