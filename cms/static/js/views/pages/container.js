/**
 * XBlockContainerPage is used to display Studio's container page for an xblock which has children.
 * This page allows the user to understand and manipulate the xblock and its children.
 */
define(['jquery', 'underscore', 'backbone', 'gettext', 'js/views/pages/base_page',
    'common/js/components/utils/view_utils', 'js/views/container', 'js/views/xblock',
    'js/views/components/add_xblock', 'js/views/modals/edit_xblock', 'js/views/modals/move_xblock_modal',
    'js/views/modals/copy_xblock_modal',
    'js/models/xblock_info', 'js/views/xblock_string_field_editor', 'js/views/xblock_access_editor',
    'js/views/pages/container_subviews', 'js/views/unit_outline', 'js/views/utils/xblock_utils'],
function($, _, Backbone, gettext, BasePage, ViewUtils, ContainerView, XBlockView, AddXBlockComponent,
    EditXBlockModal, MoveXBlockModal, CopyXBlockModal, XBlockInfo, XBlockStringFieldEditor, XBlockAccessEditor,
    ContainerSubviews, UnitOutlineView, XBlockUtils) {
    'use strict';
    var XBlockContainerPage = BasePage.extend({
        // takes XBlockInfo as a model

        events: {
            'click .edit-button': 'editXBlock',
            'click .access-button': 'editVisibilitySettings',
            'click .duplicate-button': 'duplicateXBlock',
            'click .copy-button': 'copyXBlock',
            'click .move-button': 'showMoveXBlockModal',
            'click .copy-button-custom': 'showCopyXBlockModal',
            'click .delete-button': 'deleteXBlock',
            'click .button-copy-to-library': 'copyToLibrary',
            'click .header-select input': 'toggleXBlockSelectedState',
            'click .show-actions-menu-button': 'showXBlockActionsMenu',
            'click .new-component-button': 'scrollToNewComponentButtons'
        },

        options: {
            collapsedClass: 'is-collapsed',
            canEdit: true // If not specified, assume user has permission to make changes
        },

        view: 'container_preview',


        defaultViewClass: ContainerView,

        // Overridable by subclasses-- determines whether the XBlock component
        // addition menu is added on initialization. You may set this to false
        // if your subclass handles it.
        components_on_init: true,

        initialize: function(options) {
            BasePage.prototype.initialize.call(this, options);
            this.viewClass = options.viewClass || this.defaultViewClass;
            this.isLibraryPage = (this.model.attributes.category === 'library');
            this.nameEditor = new XBlockStringFieldEditor({
                el: this.$('.wrapper-xblock-field'),
                model: this.model
            });
            this.nameEditor.render();
            if (!this.isLibraryPage) {
                this.accessEditor = new XBlockAccessEditor({
                    el: this.$('.wrapper-xblock-field')
                });
                this.accessEditor.render();
            }
            if (this.options.action === 'new') {
                this.nameEditor.$('.xblock-field-value-edit').click();
            }
            this.xblockView = this.getXBlockView();
            this.messageView = new ContainerSubviews.MessageView({
                el: this.$('.container-message'),
                model: this.model
            });
            this.messageView.render();
            if (this.isLibraryPage) {
                this.containerActionsView = new ContainerSubviews.ContainerActionsView({
                    el: this.$('.container-actions'),
                    model: this.model
                });
                this.containerActionsView.render();
            }
            // Display access message on units and split test components
            if (!this.isLibraryPage) {
                this.containerAccessView = new ContainerSubviews.ContainerAccess({
                    el: this.$('.container-access'),
                    model: this.model
                });
                this.containerAccessView.render();

                this.xblockPublisher = new ContainerSubviews.Publisher({
                    el: this.$('#publish-unit'),
                    model: this.model,
                    // When "Discard Changes" is clicked, the whole page must be re-rendered.
                    renderPage: this.render
                });
                this.xblockPublisher.render();

                this.publishHistory = new ContainerSubviews.PublishHistory({
                    el: this.$('#publish-history'),
                    model: this.model
                });
                this.publishHistory.render();

                this.viewLiveActions = new ContainerSubviews.ViewLiveButtonController({
                    el: this.$('.nav-actions'),
                    model: this.model
                });
                this.viewLiveActions.render();

                this.unitOutlineView = new UnitOutlineView({
                    el: this.$('.wrapper-unit-overview'),
                    model: this.model
                });
                this.unitOutlineView.render();
            }

            this.listenTo(Backbone, 'move:onXBlockMoved', this.onXBlockMoved);
            this.listenTo(Backbone, 'ready:onXBlockReady', this.onXBlockReady);
        },

        getViewParameters: function() {
            return {
                el: this.$('.wrapper-xblock'),
                model: this.model,
                view: this.view
            };
        },

        getXBlockView: function() {
            return new this.viewClass(this.getViewParameters());
        },

        render: function(options) {
            var self = this,
                xblockView = this.xblockView,
                loadingElement = this.$('.ui-loading'),
                unitLocationTree = this.$('.unit-location'),
                containerActions = this.$('.container-actions'),
                hiddenCss = 'is-hidden';

            loadingElement.removeClass(hiddenCss);

            // Hide both blocks until we know which one to show
            xblockView.$el.addClass(hiddenCss);

            // Render the xblock
            xblockView.render({
                done: function() {
                    // Show the xblock and hide the loading indicator
                    xblockView.$el.removeClass(hiddenCss);
                    loadingElement.addClass(hiddenCss);

                    // Notify the runtime that the page has been successfully shown
                    xblockView.notifyRuntime('page-shown', self);

                    if (self.components_on_init) {
                        // Render the add buttons. Paged containers should do this on their own.
                        self.renderAddXBlockComponents();
                    }

                    // Refresh the views now that the xblock is visible
                    self.onXBlockRefresh(xblockView);
                    unitLocationTree.removeClass(hiddenCss);
                    containerActions.removeClass(hiddenCss);

                    // Re-enable Backbone events for any updated DOM elements
                    self.delegateEvents();
                },
                block_added: options && options.block_added
            });
        },

        findXBlockElement: function(target) {
            return $(target).closest('.studio-xblock-wrapper');
        },

        getURLRoot: function() {
            return this.xblockView.model.urlRoot;
        },

        onXBlockRefresh: function(xblockView, block_added, is_duplicate) {
            this.xblockView.refresh(xblockView, block_added, is_duplicate);
            // Update publish and last modified information from the server.
            this.model.fetch();
        },

        renderAddXBlockComponents: function() {
            var self = this;
            if (self.options.canEdit) {
                this.$('.add-xblock-component').each(function(index, element) {
                    var component = new AddXBlockComponent({
                        el: element,
                        createComponent: _.bind(self.createComponent, self),
                        collection: self.options.templates
                    });
                    component.render();
                });
            } else {
                this.$('.add-xblock-component').remove();
            }
        },

        isXBlockSelected(xblockElement) {
            var xblockInfo = XBlockUtils.findXBlockInfo(xblockElement, this.model)
            return this.model.get('selected_children').includes(xblockInfo.id)
        },

        selectXBlock: function(xblockElement) {
            var xblockInfo = XBlockUtils.findXBlockInfo(xblockElement, this.model)
            var selectedChildren = this.model.get('selected_children').slice()
            selectedChildren.push(xblockInfo.id)
            this.model.set('selected_children', selectedChildren)
            xblockElement.prop('checked', true);
        },

        unselectXBlock: function(xblockElement) {
            var xblockInfo = XBlockUtils.findXBlockInfo(xblockElement, this.model);
            var selectedChildren = this.model.get('selected_children').slice();
            var index = selectedChildren.indexOf(xblockInfo.id);
            selectedChildren.splice(index, 1);
            this.model.set('selected_children', selectedChildren);
            xblockElement.prop('checked', false);
        },

        toggleXBlockSelectedState: function(event) {
            var xblockElement = this.findXBlockElement(event.target);
            var isSelected = this.isXBlockSelected(xblockElement);
            if (isSelected) {
                this.unselectXBlock(xblockElement);
            } else {
                this.selectXBlock(xblockElement);
            }
        },

        editXBlock: function(event, options) {
            var xblockElement = this.findXBlockElement(event.target),
                self = this,
                modal = new EditXBlockModal(options);
            event.preventDefault();

            if (!options || options.view !== 'visibility_view') {
                const primaryHeader = $(event.target).closest('.xblock-header-primary')

                var useNewTextEditor = primaryHeader.attr("use-new-editor-text"),
                    useNewVideoEditor = primaryHeader.attr("use-new-editor-video"),
                    useNewProblemEditor = primaryHeader.attr("use-new-editor-problem"),
                    blockType = primaryHeader.attr("data-block-type");

                if ((useNewTextEditor === "True" && blockType === "html") ||
                        (useNewVideoEditor === "True" && blockType === "video") ||
                        (useNewProblemEditor === "True" && blockType === "problem")
                ) {
                    var destinationUrl = primaryHeader.attr("authoring_MFE_base_url") + '/' + blockType + '/' + encodeURI(primaryHeader.attr("data-usage-id"));
                    window.location.href = destinationUrl;
                    return;
                }
            }

            var xblockElement = this.findXBlockElement(event.target),
                self = this,
                modal = new EditXBlockModal(options);

            modal.edit(xblockElement, this.model, {
                readOnlyView: !this.options.canEdit,
                refresh: function() {
                    self.refreshXBlock(xblockElement, false);
                }
            });
        },

        /**
         * If the new "Actions" menu is enabled, most XBlock actions like
         * Duplicate, Move, Delete, Manage Access, etc. are moved into this
         * menu. For this event, we just toggle displaying the menu.
         * @param {*} event
         */
        showXBlockActionsMenu: function(event) {
            const showActionsButton = event.currentTarget;
            const subMenu = showActionsButton.parentElement.querySelector(".wrapper-nav-sub");
            // Code in 'base.js' normally handles toggling these dropdowns but since this one is
            // not present yet during the domReady event, we have to handle displaying it ourselves.
            subMenu.classList.toggle("is-shown");
            // if propagation is not stopped, the event will bubble up to the
            // body element, which will close the dropdown.
            event.stopPropagation();
        },

        editVisibilitySettings: function(event) {
            this.editXBlock(event, {
                view: 'visibility_view',
                // Translators: "title" is the name of the current component or unit being edited.
                titleFormat: gettext('Editing access for: {title}'),
                viewSpecificClasses: '',
                modalSize: 'med'
            });
        },

        duplicateXBlock: function(event) {
            event.preventDefault();
            this.duplicateComponent(this.findXBlockElement(event.target));
        },

        showMoveXBlockModal: function(event) {
            var xblockElement = this.findXBlockElement(event.target),
                parentXBlockElement = xblockElement.parents('.studio-xblock-wrapper'),
                modal = new MoveXBlockModal({
                    sourceXBlockInfo: XBlockUtils.findXBlockInfo(xblockElement, this.model),
                    sourceParentXBlockInfo: XBlockUtils.findXBlockInfo(parentXBlockElement, this.model),
                    XBlockURLRoot: this.getURLRoot(),
                    outlineURL: this.options.outlineURL
                });

            event.preventDefault();
            modal.show();
        },

        showCopyXBlockModal: function(event) {
            var xblockElement = this.findXBlockElement(event.target),
                parentXBlockElement = xblockElement.parents('.studio-xblock-wrapper'),
                modal = new CopyXBlockModal({
                    sourceXBlockInfo: XBlockUtils.findXBlockInfo(xblockElement, this.model),
                    sourceParentXBlockInfo: XBlockUtils.findXBlockInfo(parentXBlockElement, this.model),
                    XBlockURLRoot: this.getURLRoot(),
                    outlineURL: this.options.outlineURL
                });

            event.preventDefault();
            modal.show();
        },

        copyToLibrary: function(event) {
            var xblockElement = this.findXBlockElement(event.target),
                parentXBlockElement = xblockElement.parents('.studio-xblock-wrapper'),
                modal = new CopyXBlockModal({
                    sourceXBlockInfo: XBlockUtils.findXBlockInfo(parentXBlockElement, this.model),
                    sourceParentXBlockInfo: XBlockUtils.findXBlockInfo(parentXBlockElement, this.model),
                    XBlockURLRoot: this.getURLRoot(),
                    outlineURL: this.options.outlineURL,
                    copyLibToLib: true
                });

            event.preventDefault();
            modal.show();
        },

        deleteXBlock: function(event) {
            event.preventDefault();
            this.deleteComponent(this.findXBlockElement(event.target));
        },

        createPlaceholderElement: function() {
            return $('<div/>', {class: 'studio-xblock-wrapper'});
        },

        createComponent: function(template, target) {
            // A placeholder element is created in the correct location for the new xblock
            // and then onNewXBlock will replace it with a rendering of the xblock. Note that
            // for xblocks that can't be replaced inline, the entire parent will be refreshed.
            var parentElement = this.findXBlockElement(target),
                parentLocator = parentElement.data('locator'),
                buttonPanel = target.closest('.add-xblock-component'),
                listPanel = buttonPanel.prev(),
                scrollOffset = ViewUtils.getScrollOffset(buttonPanel),
                $placeholderEl = $(this.createPlaceholderElement()),
                requestData = _.extend(template, {
                    parent_locator: parentLocator
                }),
                placeholderElement;
            placeholderElement = $placeholderEl.appendTo(listPanel);
            return $.postJSON(this.getURLRoot() + '/', requestData,
                _.bind(this.onNewXBlock, this, placeholderElement, scrollOffset, false))
                .fail(function() {
                    // Remove the placeholder if the update failed
                    placeholderElement.remove();
                });
        },

        copyXBlock: function(event) {
            event.preventDefault();
            // This is a new feature, hidden behind a feature flag.
            alert("Copying of XBlocks is coming soon.");
        },

        duplicateComponent: function(xblockElement) {
            // A placeholder element is created in the correct location for the duplicate xblock
            // and then onNewXBlock will replace it with a rendering of the xblock. Note that
            // for xblocks that can't be replaced inline, the entire parent will be refreshed.
            var self = this,
                parentElement = self.findXBlockElement(xblockElement.parent()),
                scrollOffset = ViewUtils.getScrollOffset(xblockElement),
                $placeholderEl = $(self.createPlaceholderElement()),
                placeholderElement;

            placeholderElement = $placeholderEl.insertAfter(xblockElement);
            XBlockUtils.duplicateXBlock(xblockElement, parentElement)
                .done(function(data) {
                    self.onNewXBlock(placeholderElement, scrollOffset, true, data);
                })
                .fail(function() {
                    // Remove the placeholder if the update failed
                    placeholderElement.remove();
                });
        },

        deleteComponent: function(xblockElement) {
            var self = this,
                xblockInfo = new XBlockInfo({
                    id: xblockElement.data('locator')
                });
            XBlockUtils.deleteXBlock(xblockInfo).done(function() {
                self.onDelete(xblockElement);
            });
        },

        onDelete: function(xblockElement) {
            // unselect element
            this.unselectXBlock(xblockElement)
            // get the parent so we can remove this component from its parent.
            var xblockView = this.xblockView,
                parent = this.findXBlockElement(xblockElement.parent());
            xblockElement.remove();

            // Inform the runtime that the child has been deleted in case
            // other views are listening to deletion events.
            xblockView.acknowledgeXBlockDeletion(parent.data('locator'));

            // Update publish and last modified information from the server.
            this.model.fetch();
        },

        /*
         * After move operation is complete, updates the xblock information from server .
         */
        onXBlockMoved: function() {
            this.model.fetch();
        },

        onXBlockReady: function() {
            var selectedChildren = this.model.get('selected_children');
            var xblockElements = this.$('.studio-xblock-wrapper .header-select input');
            xblockElements.each(function(index, element) {
                $(element).prop('checked', selectedChildren.includes(element.id));
            });
        },

        onNewXBlock: function(xblockElement, scrollOffset, is_duplicate, data) {
            var useNewTextEditor = this.$('.xblock-header-primary').attr("use-new-editor-text"),
                useNewVideoEditor = this.$('.xblock-header-primary').attr("use-new-editor-video"),
                useNewProblemEditor = this.$('.xblock-header-primary').attr("use-new-editor-problem");

            // find the block type in the locator if availible
            if (data.hasOwnProperty('locator')) {
                var matchBlockTypeFromLocator = /\@(.*?)\+/;
                var blockType = data.locator.match(matchBlockTypeFromLocator);
            }
            if ((useNewTextEditor === "True" && blockType.includes("html")) ||
                    (useNewVideoEditor === "True" && blockType.includes("video")) ||
                    (useNewProblemEditor === "True" && blockType.includes("problem"))
            ) {
                var destinationUrl = this.$('.xblock-header-primary').attr("authoring_MFE_base_url") + '/' + blockType[1] + '/' + encodeURI(data.locator);
                window.location.href = destinationUrl;
                return;
            }
            ViewUtils.setScrollOffset(xblockElement, scrollOffset);
            xblockElement.data('locator', data.locator);
            return this.refreshXBlock(xblockElement, true, is_duplicate);
        },

        /**
         * Refreshes the specified xblock's display. If the xblock is an inline child of a
         * reorderable container then the element will be refreshed inline. If not, then the
         * parent container will be refreshed instead.
         * @param element An element representing the xblock to be refreshed.
         * @param block_added Flag to indicate that new block has been just added.
         */
        refreshXBlock: function(element, block_added, is_duplicate) {
            var xblockElement = this.findXBlockElement(element),
                parentElement = xblockElement.parent(),
                rootLocator = this.xblockView.model.id;
            if (xblockElement.length === 0 || xblockElement.data('locator') === rootLocator) {
                this.render({refresh: true, block_added: block_added});
            } else if (parentElement.hasClass('reorderable-container')) {
                this.refreshChildXBlock(xblockElement, block_added, is_duplicate);
            } else {
                this.refreshXBlock(this.findXBlockElement(parentElement));
            }
        },

        /**
         * Refresh an xblock element inline on the page, using the specified xblockInfo.
         * Note that the element is removed and replaced with the newly rendered xblock.
         * @param xblockElement The xblock element to be refreshed.
         * @param block_added Specifies if a block has been added, rather than just needs
         * refreshing.
         * @returns {jQuery promise} A promise representing the complete operation.
         */
        refreshChildXBlock: function(xblockElement, block_added, is_duplicate) {
            var self = this,
                xblockInfo,
                TemporaryXBlockView,
                temporaryView;
            xblockInfo = new XBlockInfo({
                id: xblockElement.data('locator')
            });
            // There is only one Backbone view created on the container page, which is
            // for the container xblock itself. Any child xblocks rendered inside the
            // container do not get a Backbone view. Thus, create a temporary view
            // to render the content, and then replace the original element with the result.
            TemporaryXBlockView = XBlockView.extend({
                updateHtml: function(element, html) {
                    // Replace the element with the new HTML content, rather than adding
                    // it as child elements.
                    this.$el = $(html).replaceAll(element); // xss-lint: disable=javascript-jquery-insertion
                }
            });
            temporaryView = new TemporaryXBlockView({
                model: xblockInfo,
                view: self.xblockView.new_child_view,
                el: xblockElement
            });
            return temporaryView.render({
                success: function() {
                    self.onXBlockRefresh(temporaryView, block_added, is_duplicate);
                    temporaryView.unbind();  // Remove the temporary view
                },
                initRuntimeData: this
            });
        },

        scrollToNewComponentButtons: function(event) {
            event.preventDefault();
            $.scrollTo(this.$('.add-xblock-component'), {duration: 250});
        }
    });

    return XBlockContainerPage;
}); // end define();
