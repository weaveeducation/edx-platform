/**
 * Subviews (usually small side panels) for XBlockContainerPage.
 */
define(['jquery', 'underscore', 'gettext', 'js/views/baseview', 'common/js/components/utils/view_utils',
    'js/views/utils/xblock_utils', 'js/views/utils/move_xblock_utils', 'js/views/modals/copy_to_libraries', 'edx-ui-toolkit/js/utils/html-utils'],
    function($, _, gettext, BaseView, ViewUtils, XBlockViewUtils, MoveXBlockUtils, CopyToLibraryModal, HtmlUtils) {
        'use strict';

        var disabledCss = 'is-disabled';

        /**
         * A view that refreshes the view when certain values in the XBlockInfo have changed
         * after a server sync operation.
         */
        var ContainerStateListenerView = BaseView.extend({

            // takes XBlockInfo as a model
            initialize: function() {
                this.model.on('sync', this.onSync, this);
            },

            onSync: function(model) {
                if (this.shouldRefresh(model)) {
                    this.render();
                }
            },

            shouldRefresh: function(model) {
                return false;
            },

            render: function() {}
        });

        var ContainerActionsView = BaseView.extend({
            events: {
                'click .copy-to-libraries-button': 'onCopyToLibraries',
            },

            initialize: function() {
                this.template = this.loadTemplate('container-actions');
                this.model.on('change:selected_children', this.render, this);
            },

            render: function() {
                HtmlUtils.setHtml(
                    this.$el,
                    HtmlUtils.HTML(
                        this.template({
                            selected_children_count: this.model.get('selected_children').length
                        })
                    )
                );
                return this;
            },

            onCopyToLibraries: function(event) {
                // var xblockElement = this.findXBlockElement(event.target),
                    // parentXBlockElement = xblockElement.parents('.studio-xblock-wrapper'),
                var modal = new CopyToLibraryModal({
                    model: this.model,
                    selectedXblocks: this.model.get('selected_children')
                    // onSave: this.refresh.bind(this),
                });

                event.preventDefault();
                modal.show();
            }
        });

        var ContainerAccess = ContainerStateListenerView.extend({
            initialize: function() {
                ContainerStateListenerView.prototype.initialize.call(this);
                this.template = this.loadTemplate('container-access');
            },

            shouldRefresh: function(model) {
                return ViewUtils.hasChangedAttributes(model, ['has_partition_group_components', 'user_partitions']);
            },

            render: function() {
                HtmlUtils.setHtml(
                    this.$el,
                    HtmlUtils.HTML(
                        this.template({
                            hasPartitionGroupComponents: this.model.get('has_partition_group_components'),
                            userPartitionInfo: this.model.get('user_partition_info')
                        })
                    )
                );
                return this;
            }
        });

        var MessageView = ContainerStateListenerView.extend({
            initialize: function() {
                ContainerStateListenerView.prototype.initialize.call(this);
                this.template = this.loadTemplate('container-message');
            },

            shouldRefresh: function(model) {
                return ViewUtils.hasChangedAttributes(model, ['currently_visible_to_students']);
            },

            render: function() {
                HtmlUtils.setHtml(
                    this.$el,
                    HtmlUtils.HTML(
                        this.template({currentlyVisibleToStudents: this.model.get('currently_visible_to_students')})
                    )
                );
                return this;
            }
        });

        /**
         * A controller for updating the "View Live" button.
         */
        var ViewLiveButtonController = ContainerStateListenerView.extend({
            shouldRefresh: function(model) {
                return ViewUtils.hasChangedAttributes(model, ['published']);
            },

            render: function() {
                var viewLiveAction = this.$el.find('.button-view');
                if (this.model.get('published')) {
                    viewLiveAction.removeClass(disabledCss).attr('aria-disabled', false);
                } else {
                    viewLiveAction.addClass(disabledCss).attr('aria-disabled', true);
                }
            }
        });

        /**
         * Publisher is a view that supports the following:
         * 1) Publishing of a draft version of an xblock.
         * 2) Discarding of edits in a draft version.
         * 3) Display of who last edited the xblock, and when.
         * 4) Display of publish status (published, published with changes, changes with no published version).
         */
        var Publisher = BaseView.extend({
            events: {
                'click .action-publish': 'publish',
                'click .action-discard': 'discardChanges',
                'click .action-staff-lock': 'toggleStaffLock',
                'click .action-list-versions': 'getListVersions',
                'click .version-to-restore-link': 'restoreVersion'
            },

            // takes XBlockInfo as a model

            initialize: function() {
                BaseView.prototype.initialize.call(this);
                this.template = this.loadTemplate('publish-xblock');
                this.model.on('sync', this.onSync, this);
                this.renderPage = this.options.renderPage;
                this.versionsListProgress = false;
                this.versionsRestoreInProgress = false;
                this.versionsData = {};
            },

            onSync: function(model) {
                if (ViewUtils.hasChangedAttributes(model, [
                    'has_changes', 'published', 'edited_on', 'edited_by', 'visibility_state',
                    'has_explicit_staff_lock'
                ])) {
                    this.render();
                }
            },

            render: function() {
                HtmlUtils.setHtml(
                    this.$el,
                    HtmlUtils.HTML(
                        this.template({
                            visibilityState: this.model.get('visibility_state'),
                            visibilityClass: XBlockViewUtils.getXBlockVisibilityClass(
                                this.model.get('visibility_state')
                            ),
                            hasChanges: this.model.get('has_changes'),
                            editedOn: this.model.get('edited_on'),
                            editedBy: this.model.get('edited_by'),
                            published: this.model.get('published'),
                            publishedOn: this.model.get('published_on'),
                            publishedBy: this.model.get('published_by'),
                            released: this.model.get('released_to_students'),
                            releaseDate: this.model.get('release_date'),
                            releaseDateFrom: this.model.get('release_date_from'),
                            hasExplicitStaffLock: this.model.get('has_explicit_staff_lock'),
                            staffLockFrom: this.model.get('staff_lock_from'),
                            course: window.course,
                            HtmlUtils: HtmlUtils
                        })
                    )
                );

                return this;
            },

            publish: function(e) {
                var xblockInfo = this.model;
                if (e && e.preventDefault) {
                    e.preventDefault();
                }
                ViewUtils.runOperationShowingMessage(gettext('Publishing'),
                    function() {
                        return xblockInfo.save({publish: 'make_public'}, {patch: true});
                    }).always(function() {
                        xblockInfo.set('publish', null);
                        // Hide any move notification if present.
                        MoveXBlockUtils.hideMovedNotification();
                    }).done(function() {
                        xblockInfo.fetch();
                    });
            },

            discardChanges: function(e) {
                var xblockInfo = this.model,
                    renderPage = this.renderPage;
                if (e && e.preventDefault) {
                    e.preventDefault();
                }
                ViewUtils.confirmThenRunOperation(gettext('Discard Changes'),
                    gettext('Are you sure you want to revert to the last published version of the unit? You cannot undo this action.'),
                    gettext('Discard Changes'),
                    function() {
                        ViewUtils.runOperationShowingMessage(gettext('Discarding Changes'),
                            function() {
                                return xblockInfo.save({publish: 'discard_changes'}, {patch: true});
                            }).always(function() {
                                xblockInfo.set('publish', null);
                                // Hide any move notification if present.
                                MoveXBlockUtils.hideMovedNotification();
                            }).done(function() {
                                renderPage();
                            });
                    }
                );
            },

            toggleStaffLock: function(e) {
                var xblockInfo = this.model,
                    self = this,
                    enableStaffLock, hasInheritedStaffLock,
                    saveAndPublishStaffLock, revertCheckBox;
                if (e && e.preventDefault) {
                    e.preventDefault();
                }
                enableStaffLock = !xblockInfo.get('has_explicit_staff_lock');
                hasInheritedStaffLock = xblockInfo.get('ancestor_has_staff_lock');

                revertCheckBox = function() {
                    self.checkStaffLock(!enableStaffLock);
                };

                saveAndPublishStaffLock = function() {
                    // Setting staff lock to null when disabled will delete the field from this xblock,
                    // allowing it to use the inherited value instead of using false explicitly.
                    return xblockInfo.save({
                        publish: 'republish',
                        metadata: {visible_to_staff_only: enableStaffLock ? true : null}},
                        {patch: true}
                    ).always(function() {
                        xblockInfo.set('publish', null);
                    }).done(function() {
                        xblockInfo.fetch();
                    }).fail(function() {
                        revertCheckBox();
                    });
                };

                this.checkStaffLock(enableStaffLock);
                if (enableStaffLock && !hasInheritedStaffLock) {
                    ViewUtils.runOperationShowingMessage(gettext('Hiding from Students'),
                        _.bind(saveAndPublishStaffLock, self));
                } else if (enableStaffLock && hasInheritedStaffLock) {
                    ViewUtils.runOperationShowingMessage(gettext('Explicitly Hiding from Students'),
                        _.bind(saveAndPublishStaffLock, self));
                } else if (!enableStaffLock && hasInheritedStaffLock) {
                    ViewUtils.runOperationShowingMessage(gettext('Inheriting Student Visibility'),
                        _.bind(saveAndPublishStaffLock, self));
                } else {
                    ViewUtils.confirmThenRunOperation(gettext('Make Visible to Students'),
                        gettext('If the unit was previously published and released to students, any changes you made to the unit when it was hidden will now be visible to students. Do you want to proceed?'),
                        gettext('Make Visible to Students'),
                        function() {
                            ViewUtils.runOperationShowingMessage(gettext('Making Visible to Students'),
                                _.bind(saveAndPublishStaffLock, self));
                        },
                        function() {
                            // On cancel, revert the check in the check box
                            revertCheckBox();
                        }
                    );
                }
            },

            getListVersions: function(e) {
                var self = this;
                if (this.versionsListProgress) {
                    return;
                }
                this.versionsListProgress = true;
                this.$el.find('.versions-list').html('Loading...');
                $.ajax({
                    url: '/get_versions_list/' + this.model.get('id'),
                    type: 'GET',
                    dataType: 'json',
                    success: function(data) {
                        self.versionsListProgress = false;
                        if (data.versions.length > 0) {
                            var versionsHtml = '';
                            $.each(data.versions, function(idx, val) {
                                self.versionsData[val.id] = val;
                                versionsHtml += '<div class="version-to-restore">' +
                                  '<div>' + val.datetime + '</div>' +
                                  '<div>by ' + val.user + ' | <a href="javascript: void(0);" class="version-to-restore-link ' + (val.can_restore ? 'can-restore' : 'cant-restore') + '" data-version-id="' + val.id + '">' + (val.can_restore ? 'Restore' : 'Current Version') + '</a></div>' +
                                  '</div>';
                            });
                            self.$el.find('.versions-list').html(versionsHtml);
                        } else {
                            self.$el.find('.versions-list').html('Previous versions not found');
                        }
                    }
                });
            },

            restoreVersion: function(e) {
                var self = this;
                if ((this.versionsRestoreInProgress) || ($(e.target).hasClass('cant-restore'))) {
                    return;
                }
                var versionId = $(e.target).data('version-id');
                var version = this.versionsData[versionId];
                if (window.confirm("Do you wish to revert to this previously published version (" + (version.datetime + ' - ' + version.user) + ")?")) {
                    this.versionsRestoreInProgress = true;
                    ViewUtils.runOperationShowingMessage(gettext('Restore in progress. Please wait'),
                        function() {
                            return $.ajax({
                                url: '/restore_block_version/' + self.model.get('id'),
                                type: 'POST',
                                data: {versionId: versionId},
                                dataType: 'json',
                                success: function(data) {
                                    if (data.success) {
                                        location.reload();
                                    }
                                }
                            });
                        }).always(function() {
                        }).done(function() {
                        });
                }
            },

            checkStaffLock: function(check) {
                this.$('.action-staff-lock i').removeClass('fa-check-square-o fa-square-o');
                this.$('.action-staff-lock i').addClass(check ? 'fa-check-square-o' : 'fa-square-o');
            }
        });

        /**
         * PublishHistory displays when and by whom the xblock was last published, if it ever was.
         */
        var PublishHistory = BaseView.extend({
            // takes XBlockInfo as a model

            initialize: function() {
                BaseView.prototype.initialize.call(this);
                this.template = this.loadTemplate('publish-history');
                this.model.on('sync', this.onSync, this);
            },

            onSync: function(model) {
                if (ViewUtils.hasChangedAttributes(model, ['published', 'published_on', 'published_by'])) {
                    this.render();
                }
            },

            render: function() {
                HtmlUtils.setHtml(
                    this.$el,
                    HtmlUtils.HTML(
                        this.template({
                            published: this.model.get('published'),
                            published_on: this.model.get('published_on'),
                            published_by: this.model.get('published_by')
                        })
                    )
                );

                return this;
            }
        });

        return {
            MessageView: MessageView,
            ViewLiveButtonController: ViewLiveButtonController,
            Publisher: Publisher,
            PublishHistory: PublishHistory,
            ContainerAccess: ContainerAccess,
            ContainerActionsView: ContainerActionsView
        };
    }); // end define();
