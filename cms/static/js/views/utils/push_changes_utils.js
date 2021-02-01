/**
 * Provides utilities for move xblock.
 */
define([
  'jquery',
  'underscore',
  'backbone',
  'js/views/modals/push_changes_to_siblings',
],
function($, _, Backbone, PushChangesToSiblingsModal) {
  var publishChanges = function(data) {

    var modal = new PushChangesToSiblingsModal({
        model: data.target,
        xblockType: data.xblockType,
        onSave: data.onSave
    });

    modal.requestCoursesWithDuplicates().then(function (sublings) {
      if (data.alwaysShow || sublings.length) {
        modal.show()
      } else {
        data.target.save({ publish: 'make_public' }, { patch: true }, data.onSave)
      }
    })
  }

  return {
    publishChanges: publishChanges
  };
});
