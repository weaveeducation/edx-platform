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
            BaseModal.prototype.initialize.call(this);
            this.copyLibToLib = this.options.copyLibToLib || false;
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
            this.isLib = (this.sourceXBlockInfo.get('id').indexOf('lib-block-v1') === 0);
            this.xblockCategory = this.sourceXBlockInfo.get('category');
            this.allowedToCopyToLib = (['problem', 'html', 'video'].indexOf(this.xblockCategory) !== -1);
            this.courses = {};
            this.copyToOtherItemType = 'course';
            if (this.copyLibToLib) {
                this.copyToOtherItemType = 'library';
            }
            this.firstRender = true;
            this.isLoading = true;

            this.listenTo(Backbone, 'move:breadcrumbRendered', this.focusModal);
            this.listenTo(Backbone, 'move:enableMoveOperation', this.enableMoveOperation);
            this.listenTo(Backbone, 'move:hideMoveModal', this.hide);
        },

        render: function() {
            var self = this;
            BaseModal.prototype.render.apply(this);

            this.copyToOtherCourseTpl = this.loadTemplate('copy-to-other-course');
            this.$('.course-listing-data').html(this.copyToOtherCourseTpl({
                isLib: this.isLib,
                selectedRadio: this.copyToOtherItemType,
                allowedToCopyToLib: this.allowedToCopyToLib,
                copyLibToLib: this.copyLibToLib
            }));

            this.$('input:radio[name="copy-to-other-item"]').change(function() {
                self.changeCopyRadio($(this).val());
            });

            this.$('.copy-to-course').change(function() {
                if (self.copyToOtherItemType === 'course') {
                    self.changeCopyToCourseSelector($(this).val());
                } else {
                    self.changeCopyToLibrarySelector($(this).val());
                }
            });

            this.changeCopyRadio(this.copyToOtherItemType);
        },

        changeCopyRadio: function(copyToOtherItemType) {
            var self = this;
            this.copyToOtherItemType = copyToOtherItemType;
            this.$('.copy-to-course').attr('disabled', 'disabled');
            this.$('input:radio[name="copy-to-other-item"]').attr('disabled', 'disabled');
            this.updateMoveState(false);
            this.showLoadingMsg();

            var fetchListing = null;
            if (this.copyToOtherItemType === 'course') {
                fetchListing = this.fetchCourseListing();
            } else {
                fetchListing = this.fetchLibraryListing();
            }

            fetchListing.done(function(items) {
                if (self.$('.course-listing').hasClass('is-hidden')) {
                    self.$('.course-listing').removeClass('is-hidden');
                }

                items.sort(function(a, b) {
                    if(a.display_name < b.display_name) return -1;
                    if(a.display_name > b.display_name) return 1;
                    return 0;
                });

                var optionText = '';
                var copyToCourseSelector = self.$('.copy-to-course');
                copyToCourseSelector.empty();
                for (var j in items) {
                    if (self.copyToOtherItemType === 'course') {
                        optionText = items[j].display_name + ' [ ' + items[j].number + ' / ' + items[j].run + ' ]';
                    } else {
                        optionText = items[j].display_name + ' [ ' + items[j].org + ' / ' + items[j].course + ' ]';
                    }
                    self.courses[items[j].course_key] = items[j];
                    copyToCourseSelector.append($("<option></option>")
                        .attr("value", items[j].course_key).text(optionText));
                }

                if (self.copyToOtherItemType === 'course') {
                    self.changeCopyToCourseSelector(items[0].course_key);
                } else {
                    self.$('input:radio[name="copy-to-other-item"]').removeAttr('disabled');
                    self.hideLoadingMsg();
                    self.changeCopyToLibrarySelector(items[0].course_key);
                }
            });
        },

        showLoadingMsg: function() {
            if (this.isLoading) {
                return;
            } else {
                this.isLoading = true;
            }

            if (this.moveXBlockListView) {
                this.moveXBlockListView.remove();
            }
            if (this.moveXBlockBreadcrumbView) {
                this.moveXBlockBreadcrumbView.remove();
            }

            if (this.$('.ui-loading').hasClass('is-hidden')) {
                this.$('.ui-loading').removeClass('is-hidden');
            }
        },

        hideLoadingMsg: function() {
            this.isLoading = false;
        },

        changeCopyToCourseSelector: function(courseKeyVal) {
            var self = this;
            this.outlineURL = this.courses[courseKeyVal].url + '?format=concise';
            this.$('.copy-to-course').attr('disabled', 'disabled');
            this.$('input:radio[name="copy-to-other-item"]').attr('disabled', 'disabled');
            this.updateMoveState(false);
            this.showLoadingMsg();

            if (this.moveXBlockListView) {
                this.moveXBlockListView.remove();
            }
            if (this.moveXBlockBreadcrumbView) {
                this.moveXBlockBreadcrumbView.remove();
            }

            if (this.firstRender) {
                this.firstRender = false;
                this.$('.course-listing').removeClass('is-hidden');
            } else {
              this.$('.ui-loading').parent()
                   .append("<div class='breadcrumb-container is-hidden'></div>")
                   .append("<div class='xblock-list-container'></div>");
            }

            this.fetchCourseOutline().done(function(courseOutlineInfo2, ancestorInfo2) {
                self.$('.copy-to-course').removeAttr('disabled');
                self.$('input:radio[name="copy-to-other-item"]').removeAttr('disabled');
                self.renderViewsAndUI(courseOutlineInfo2, ancestorInfo2);
                self.hideLoadingMsg();
            });
        },

        changeCopyToLibrarySelector: function(libraryKeyVal) {
            this.outlineURL = this.courses[libraryKeyVal].url + '?format=concise';
            this.targetParentXBlockInfo = {
                id: this.courses[libraryKeyVal].location
            };

            var selDisabled = this.$('.copy-to-course').attr('disabled');
            if ((typeof selDisabled !== typeof undefined) && (selDisabled !== false)) {
                this.$('.copy-to-course').removeAttr('disabled');
            }
            this.renderLibViewsAndUI();
            this.updateMoveState(true);
            if (this.firstRender) {
                this.firstRender = false;
            }
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

        fetchLibraryListing: function() {
            return $.when(this.fetchData('/libraries_listing'));
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

        renderLibViewsAndUI: function() {
            if (!this.$('.ui-loading').hasClass('is-hidden')) {
                this.$('.ui-loading').addClass('is-hidden');
            }
            if (!this.$('.breadcrumb-container').hasClass('is-hidden')) {
                this.$('.breadcrumb-container').addClass('is-hidden');
            }
            if (this.$('.xblock-list-container').length && !this.$('.xblock-list-container').hasClass('is-hidden')) {
                this.$('.xblock-list-container').addClass('is-hidden');
            }
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
                    targetParentLocator: this.targetParentXBlockInfo.id,
                    copyLibToLib: this.copyLibToLib
                }
            );
        }
    });

    return CopyXBlockModal;
});
