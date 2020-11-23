/**
 * PagedXBlockContainerPage is a variant of XBlockContainerPage that supports Pagination.
 */
define(['jquery', 'underscore', 'gettext', 'js/views/pages/container', 'js/views/paged_container'],
    function($, _, gettext, XBlockContainerPage, PagedContainerView) {
        'use strict';
        var PagedXBlockContainerPage = XBlockContainerPage.extend({

            events: _.extend({}, XBlockContainerPage.prototype.events, {
                'click .toggle-preview-button': 'toggleChildrenPreviews'
            }),

            defaultViewClass: PagedContainerView,
            components_on_init: false,

            initialize: function(options) {
                this.tagSelectors = {};
                this.selectedTags = {};
                this.tagsSelected = false;
                this.page_size = options.page_size || 10;
                this.showChildrenPreviews = options.showChildrenPreviews || true;
                XBlockContainerPage.prototype.initialize.call(this, options);
            },

            getViewParameters: function() {
                return _.extend(XBlockContainerPage.prototype.getViewParameters.call(this), {
                    page_size: this.page_size,
                    page: this
                });
            },

            refreshXBlock: function(element, block_added, is_duplicate) {
                var xblockElement = this.findXBlockElement(element),
                    rootLocator = this.xblockView.model.id;
                if (xblockElement.length === 0 || xblockElement.data('locator') === rootLocator) {
                    this.render({refresh: true, block_added: block_added});
                } else {
                    this.refreshChildXBlock(xblockElement, block_added, is_duplicate);
                }
            },

            toggleChildrenPreviews: function(xblockElement) {
                xblockElement.preventDefault();
                this.xblockView.togglePreviews();
            },

            updatePreviewButton: function(show_previews) {
                var text = (show_previews) ? gettext('Hide Previews') : gettext('Show Previews'),
                    $button = $('.nav-actions .button-toggle-preview');

                this.$('.preview-text', $button).text(text);
                this.$('.toggle-preview-button').removeClass('is-hidden');
            },

            renderFilters: function() {
                var self = this;
                this.$('.tag-filter').each(function() {
                    var tagName = $(this).attr('name');
                    var ms = $(this).magicSuggest({
                        data: $(this).data('values'),
                        width: 700,
                        allowFreeEntries: false,
                        maxSelection: 1000
                    });
                    self.tagSelectors[tagName] = ms;
                    $(ms).on('selectionchange', function(e, m) {
                        var tagValues = this.getValue();
                        if (tagValues.length > 0) {
                            self.selectedTags[tagName] = this.getValue();
                            self.tagsSelected = true;
                        } else if (tagName in self.selectedTags) {
                            delete self.selectedTags[tagName];
                            if ($.isEmptyObject(self.selectedTags)) {
                                self.tagsSelected = false;
                            }
                        }
                        self.updatePageOnFilterChange();
                    });
                });
                this.$('.tags_clear_all').click(function() {
                    if (!self.tagsSelected) {
                        return;
                    }
                    $.each(self.tagSelectors, function(tagName) {
                        self.tagSelectors[tagName].clear();
                    });
                    self.selectedTags = {};
                    self.tagsSelected = false;
                    self.updatePageOnFilterChange();
                });
            },

            updatePageOnFilterChange: function() {
                var self = this;
                var loadingElement = this.$('.ui-loading'),
                    contentPrimary = this.$('.library-main-listing'),
                    hiddenCss = 'is-hidden';

                contentPrimary.addClass(hiddenCss);
                loadingElement.removeClass(hiddenCss);

                this.xblockView.renderPage({
                    page_number: 0,
                    tags: this.selectedTags,
                    done: function() {
                        contentPrimary.removeClass(hiddenCss);
                        loadingElement.addClass(hiddenCss);
                        if (self.tagsSelected) {
                            self.xblockView.pagingHeader.hide();
                            self.xblockView.pagingFooter.hide();
                            self.$el.find('.add-xblock-component-button').attr('disabled', 'disabled');
                        } else {
                            self.xblockView.pagingHeader.show();
                            self.xblockView.pagingFooter.show();
                            self.$el.find('.add-xblock-component-button').removeAttr('disabled');
                        }
                    }
                });
            }

        });
        return PagedXBlockContainerPage;
    });
