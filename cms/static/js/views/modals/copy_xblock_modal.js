/**
 * The CopyXblockModal to copy XBlocks in course.
 */
define([
    'jquery',
    'backbone',
    'underscore',
    'gettext',
    'js/views/baseview',
    'js/views/utils/xblock_utils',
    'js/views/utils/copy_xblock_utils',
    'edx-ui-toolkit/js/utils/html-utils',
    'edx-ui-toolkit/js/utils/string-utils',
    'common/js/components/views/feedback',
    'js/models/xblock_info',
    'js/views/modals/base_modal',
    'js/views/move_xblock_list',
    'js/views/move_xblock_breadcrumb'
],
function($, Backbone, _, gettext, BaseView, XBlockViewUtils, CopyXBlockUtils, HtmlUtils, StringUtils, Feedback,
         XBlockInfoModel, BaseModal, MoveXBlockListView, MoveXBlockBreadcrumbView) {
    'use strict';

    var CopyXBlockModal = BaseModal.extend({
        events: _.extend({}, BaseModal.prototype.events, {
            'click .action-move:not(.is-disabled)': 'copyXBlock'
        }),

        options: $.extend({}, BaseModal.prototype.options, {
            modalName: 'move-xblock',
            modalSize: 'lg',
            showEditorModeButtons: false,
            addPrimaryActionButton: true,
            primaryActionButtonType: 'move',
            viewSpecificClasses: 'move-modal',
            primaryActionButtonTitle: gettext('Copy'),
            modalSRTitle: gettext('Choose a location to copy your component to')
        }),

        initialize: function() {
            var self = this;
            BaseModal.prototype.initialize.call(this);
            this.sourceXBlockInfo = this.options.sourceXBlockInfo;
            this.sourceParentXBlockInfo = this.options.sourceParentXBlockInfo;
            this.targetParentXBlockInfo = null;
            this.XBlockURLRoot = this.options.XBlockURLRoot;
            this.XBlockAncestorInfoURL = StringUtils.interpolate(
                '{urlRoot}/{usageId}?fields=ancestorInfo',
                {urlRoot: this.XBlockURLRoot, usageId: this.sourceXBlockInfo.get('id')}
            );
            this.outlineURL = this.options.outlineURL;
            this.options.title = this.getTitle();
            this.courses = {};
            this.fetchCourseListing().done(function(data) {
                data.sort(function(a, b) {
                    if(a.display_name < b.display_name) return -1;
                    if(a.display_name > b.display_name) return 1;
                    return 0;
                });
                for (var i in data) {
                    self.courses[data[i].course_key] = data[i];
                }
                self.outlineURL = data[0].url + '?format=concise';

                self.copyToOtherCourseTpl = self.loadTemplate('copy-to-other-course');
                self.$('.course-listing').removeClass('is-hidden');
                self.$('.course-listing-data').html(self.copyToOtherCourseTpl({courses: data}));

                self.fetchCourseOutline().done(function(courseOutlineInfo, ancestorInfo) {
                    self.$('.copy-to-course').change(function() {
                        self.$('.copy-to-course').attr('disabled', 'disabled');
                        self.outlineURL = self.courses[$(this).val()].url + '?format=concise';

                        if (self.moveXBlockListView) {
                            self.moveXBlockListView.remove();
                        }
                        if (self.moveXBlockBreadcrumbView) {
                            self.moveXBlockBreadcrumbView.remove();
                        }

                        self.$('.ui-loading').removeClass('is-hidden').parent()
                            .append("<div class='breadcrumb-container is-hidden'></div>")
                            .append("<div class='xblock-list-container'></div>");

                        self.fetchCourseOutline().done(function(courseOutlineInfo2, ancestorInfo2) {
                            self.$('.copy-to-course').removeAttr('disabled');
                            self.renderViewsAndUI(courseOutlineInfo2, ancestorInfo2);
                        });
                    });
                    self.renderViewsAndUI(courseOutlineInfo, ancestorInfo);
                });
            });

            this.listenTo(Backbone, 'move:breadcrumbRendered', this.focusModal);
            this.listenTo(Backbone, 'move:enableMoveOperation', this.enableMoveOperation);
            this.listenTo(Backbone, 'move:hideMoveModal', this.hide);
        },

        getTitle: function() {
            return StringUtils.interpolate(
                gettext('Copy: {displayName}'),
                {displayName: this.sourceXBlockInfo.get('display_name')}
            );
        },

        getContentHtml: function() {
            var moveXblockModalTpl = this.loadTemplate('move-xblock-modal');
            return moveXblockModalTpl({});
        },

        show: function() {
            BaseModal.prototype.show.apply(this, [false]);
            this.updateMoveState(false);
            CopyXBlockUtils.hideCopiedNotification();
        },

        hide: function() {
            if (this.moveXBlockListView) {
                this.moveXBlockListView.remove();
            }
            if (this.moveXBlockBreadcrumbView) {
                this.moveXBlockBreadcrumbView.remove();
            }
            BaseModal.prototype.hide.apply(this);
            Feedback.prototype.outFocus.apply(this);
        },

        resize: function() {
            // Do Nothing. Overridden to use our own styling instead of one provided by base modal
        },

        focusModal: function() {
            Feedback.prototype.inFocus.apply(this, [this.options.modalWindowClass]);
            $(this.options.modalWindowClass).focus();
        },

        fetchCourseListing: function() {
            return $.when(this.fetchData('/course_listing'));
        },

        fetchCourseOutline: function() {
            return $.when(
                this.fetchData(this.outlineURL),
                this.fetchData(this.XBlockAncestorInfoURL)
            );
        },

        fetchData: function(url) {
            var deferred = $.Deferred();
            $.ajax({
                url: url,
                contentType: 'application/json',
                dataType: 'json',
                type: 'GET'
            }).done(function(data) {
                deferred.resolve(data);
            }).fail(function() {
                deferred.reject();
            });
            return deferred.promise();
        },

        renderViewsAndUI: function(courseOutlineInfo, ancestorInfo) {
            $('.ui-loading').addClass('is-hidden');
            $('.breadcrumb-container').removeClass('is-hidden');
            this.renderViews(courseOutlineInfo, ancestorInfo);
        },

        renderViews: function(courseOutlineInfo, ancestorInfo) {
            this.moveXBlockBreadcrumbView = new MoveXBlockBreadcrumbView({});
            this.moveXBlockListView = new MoveXBlockListView(
                {
                    model: new XBlockInfoModel(courseOutlineInfo, {parse: true}),
                    sourceXBlockInfo: this.sourceXBlockInfo,
                    ancestorInfo: ancestorInfo
                }
            );
        },

        updateMoveState: function(isValidMove) {
            var $moveButton = this.$el.find('.action-move');
            if (isValidMove) {
                $moveButton.removeClass('is-disabled');
            } else {
                $moveButton.addClass('is-disabled');
            }
        },

        isValidCategory: function(targetParentXBlockInfo) {
            var basicBlockTypes = ['course', 'chapter', 'sequential', 'vertical'],
                sourceParentType = this.sourceParentXBlockInfo.get('category'),
                targetParentType = targetParentXBlockInfo.get('category'),
                sourceParentHasChildren = this.sourceParentXBlockInfo.get('has_children'),
                targetParentHasChildren = targetParentXBlockInfo.get('has_children');

            // Treat source parent component as vertical to support move child components under content experiment
            // and other similar xblocks.
            if (sourceParentHasChildren && !_.contains(basicBlockTypes, sourceParentType)) {
                sourceParentType = 'vertical';  // eslint-disable-line no-param-reassign
            }

            // Treat target parent component as a vertical to support move to parentable target parent components.
            // Also, moving a component directly to content experiment is not allowed, we need to visit to group level.
            if (targetParentHasChildren && !_.contains(basicBlockTypes, targetParentType) &&
                targetParentType !== 'split_test') {
                targetParentType = 'vertical';  // eslint-disable-line no-param-reassign
            }
            return targetParentType === sourceParentType;
        },

        enableMoveOperation: function(targetParentXBlockInfo) {
            var isValidMove = false;

            // update target parent on navigation
            this.targetParentXBlockInfo = targetParentXBlockInfo;
            if (this.isValidCategory(targetParentXBlockInfo) &&
                this.sourceParentXBlockInfo.id !== targetParentXBlockInfo.id && // same parent case
                this.sourceXBlockInfo.id !== targetParentXBlockInfo.id) { // same source item case
                isValidMove = true;
            }
            this.updateMoveState(isValidMove);
        },

        copyXBlock: function() {
            CopyXBlockUtils.copyXBlock(
                {
                    sourceXBlockElement: $("li.studio-xblock-wrapper[data-locator='" + this.sourceXBlockInfo.id + "']"),
                    sourceDisplayName: this.sourceXBlockInfo.get('display_name'),
                    sourceLocator: this.sourceXBlockInfo.id,
                    sourceParentLocator: this.sourceParentXBlockInfo.id,
                    targetParentLocator: this.targetParentXBlockInfo.id
                }
            );
        }
    });

    return CopyXBlockModal;
});
