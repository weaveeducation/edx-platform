/**
 * Provides utilities for copy xblock.
 */
define([
    'jquery',
    'underscore',
    'backbone',
    'common/js/components/views/feedback',
    'common/js/components/views/feedback_alert',
    'js/views/utils/xblock_utils',
    'edx-ui-toolkit/js/utils/string-utils'
],
function($, _, Backbone, Feedback, AlertView, XBlockViewUtils, StringUtils) {
    'use strict';
    var redirectLink, copyXBlock, undoCopyXBlock, showCopiedNotification, hideCopiedNotification;

    redirectLink = function(link) {
        window.location.href = link;
    };

    copyXBlock = function(data) {
        XBlockViewUtils.copyXBlock(data.sourceLocator, data.targetParentLocator)
        .done(function(response) {
            // hide modal
            Backbone.trigger('move:hideMoveModal');
            showCopiedNotification(
                StringUtils.interpolate(
                    gettext('Success! "{displayName}" has been copied.'),
                    {
                        displayName: data.sourceDisplayName
                    }
                ),
                {
                    sourceXBlockElement: data.sourceXBlockElement,
                    sourceDisplayName: data.sourceDisplayName,
                    sourceLocator: data.sourceLocator,
                    sourceParentLocator: data.sourceParentLocator,
                    targetParentLocator: data.targetParentLocator,
                    targetFromResponse: response.parent_locator,
                    targetIsLibrary: response.target_is_library,
                    targetIndex: response.source_index
                }
            );
            Backbone.trigger('move:onXBlockMoved');
        });
    };

    undoCopyXBlock = function(data) {
        XBlockViewUtils.moveXBlock(data.sourceLocator, data.sourceParentLocator, data.targetIndex)
        .done(function() {
            // show XBlock element
            data.sourceXBlockElement.show();
            showCopiedNotification(
                StringUtils.interpolate(
                    gettext('Copy cancelled. "{sourceDisplayName}" has been copied back to its original location.'),
                    {
                        sourceDisplayName: data.sourceDisplayName
                    }
                )
            );
            Backbone.trigger('move:onXBlockMoved');
        });
    };

    showCopiedNotification = function(title, data) {
        var copiedAlertView;
        // data is provided when we click undo move button.
        if (data) {
            copiedAlertView = new AlertView.Confirmation({
                title: title,
                actions: {
                    secondary: [
                        {
                            text: gettext('Take me to the new location'),
                            class: 'action-cancel',
                            click: function() {
                                if (data.targetIsLibrary) {
                                    redirectLink('/library/' + data.targetFromResponse);
                                } else {
                                    redirectLink('/container/' + data.targetParentLocator);
                                }
                            }
                        }
                    ]
                }
            });
        } else {
            copiedAlertView = new AlertView.Confirmation({
                title: title
            });
        }
        copiedAlertView.show();
        // scroll to top
        $.smoothScroll({
            offset: 0,
            easing: 'swing',
            speed: 1000
        });
        copiedAlertView.$('.wrapper').first().focus();
        return copiedAlertView;
    };

    hideCopiedNotification = function() {
        var copiedAlertView = Feedback.active_alert;
        if (copiedAlertView) {
            AlertView.prototype.hide.apply(copiedAlertView);
        }
    };

    return {
        redirectLink: redirectLink,
        copyXBlock: copyXBlock,
        undoCopyXBlock: undoCopyXBlock,
        showCopiedNotification: showCopiedNotification,
        hideCopiedNotification: hideCopiedNotification
    };
});
