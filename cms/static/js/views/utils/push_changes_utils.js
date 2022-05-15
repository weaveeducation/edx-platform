/**
 * Provides utilities for move xblock.
 */
define([
    'jquery',
    'underscore',
    'gettext',
    'common/js/components/utils/view_utils',
    'js/views/modals/push_changes_to_siblings'
],
function($, _, gettext, ViewUtils, PushChangesToSiblingsModal) {
    var publishChanges = function(data) {
        var modal = new PushChangesToSiblingsModal({
            model: data.target,
            xblockType: data.xblockType,
            onSave: data.onSave
        });

        ViewUtils.runOperationShowingMessage(gettext('Publishing'), function() {
            return modal.requestCoursesWithDuplicates().then(function(sublings) {
                if (data.alwaysShow || sublings.length) {
                    modal.show();
                } else {
                    return data.target.save(
                        {publish: 'make_public'},
                        {patch: true}
                    ).always(function() {
                        if (data.onSave) {
                            data.onSave();
                        }
                    });
                }
            });
        });
    };

    return {
        publishChanges: publishChanges
    };
});
