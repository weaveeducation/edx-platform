define(['jquery.form', 'js/index'], function() {
    'use strict';
    return function() {
        // showing/hiding creation rights UI
        $('.show-creationrights').click(function(e) {
            e.preventDefault();
            $(this)
                .closest('.wrapper-creationrights')
                .toggleClass('is-shown')
                .find('.ui-toggle-control')
                .toggleClass('current');
        });

        var reloadPage = function() {
            location.reload();
        };

        var showError = function() {
            $('#request-coursecreator-submit')
                .toggleClass('has-error')
                .find('.label')
                .text('Sorry, there was error with your request');
            $('#request-coursecreator-submit')
                .find('.fa-cog')
                .toggleClass('fa-spin');
        };

        $('#request-coursecreator').ajaxForm({
            error: showError,
            success: reloadPage
        });

        $('#request-coursecreator-submit').click(function(event) {
            $(this)
                .toggleClass('is-disabled is-submitting')
                .attr('aria-disabled', $(this).hasClass('is-disabled'))
                .find('.label')
                .text('Submitting Your Request');
        });

        var ms = $('#orgs-input').magicSuggest({
            data: window.orgsList,
            width: 700,
            allowFreeEntries: false,
            maxSelection: 200,
            emptyText: "Please, choose organizations...",
            inputCfg: {"aria-label": "Please, choose organizations..."}
        });
        $(ms).on('selectionchange', function(e, m) {
            $(document).trigger("orgs_changed", this.getValue());
        });
    };
});
