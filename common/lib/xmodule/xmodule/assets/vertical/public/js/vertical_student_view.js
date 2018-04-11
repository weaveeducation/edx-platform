/* JavaScript for Vertical Student View. */

if (!Set) {
    function Set(args) {
        this._items = [];

        if (args) {
            for (var i = 0; i < arguments.length; i++) {
                if (arguments[i] instanceof Array) {
                    for (var j = 0; j < arguments[i].length; j++) {
                        this.add(arguments[i][j]);
                    }
                } else {
                    this.add(arguments[i]);
                }
            }
        }
    }

    Set.prototype = {
        add: function(value) {
            if (!this.has(value)) {
                this._items.push(value);
                return true;
            }
            return false;
        },
        has: function(value) {
            return this._items.indexOf(value) > -1;
        }
    };
}

var SEEN_COMPLETABLES = new Set();

window.VerticalStudentView = function(runtime, element) {
    'use strict';
    RequireJS.require(['course_bookmarks/js/views/bookmark_button'], function(BookmarkButton) {
        var $element = $(element);
        var $bookmarkButtonElement = $element.find('.bookmark-button');

        return new BookmarkButton({
            el: $bookmarkButtonElement,
            bookmarkId: $bookmarkButtonElement.data('bookmarkId'),
            usageId: $element.data('usageId'),
            bookmarked: $element.parent('#seq_content').data('bookmarked'),
            apiUrl: $bookmarkButtonElement.data('bookmarksApiUrl')
        });
    });
    $(element).find('.vert').each(
        function(idx, block) {
            var blockKey = block.dataset.id;

            if (!block.dataset.completableByViewing) {
                return;
            }
            // TODO: EDUCATOR-1778
            // *  Check if blocks are in the browser's view window or in focus
            //    before marking complete. This will include a configurable
            //    delay so that blocks must be seen for a few seconds before
            //    being marked complete, to prevent completion via rapid
            //    scrolling.  (OC-3358)
            // *  Limit network traffic by batching and throttling calls.
            //    (OC-3090)
            if (blockKey && !SEEN_COMPLETABLES.has(blockKey)) {
                $.ajax({
                    type: 'POST',
                    url: runtime.handlerUrl(element, 'publish_completion'),
                    data: JSON.stringify({
                        block_key: blockKey,
                        completion: 1.0
                    })
                });
                SEEN_COMPLETABLES.add(blockKey);
            }
        }
    );
};
