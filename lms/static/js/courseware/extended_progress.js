$(document).ready(function() {
    $('.tags-block-info-data').each(function() {
        var label = $(this).data('label'),
            percentCorrect = $(this).data('percent-correct'),
            answers = $(this).data('answers');
        var html = '<div class="tags-tooltip-block">' +
            '<div class="tags-label">' + label + '</div>' +
            '<table class="tags-table">' +
            '<tr>' +
            '<td class="tags-percentage">' + percentCorrect + '%</td>' +
            '<td class="tags-percentage">' + answers + '</td>' +
            '</tr>' +
            '<tr>' +
            '<td class="tags-help">Percent Correct</td>' +
            '<td class="tags-help">Answers Submitted</td>' +
            '</tr>' +
            '</table>' +
            '</div>';
        $(this).tooltipsy({
            alignTo: 'cursor',
            offset: [0, 1],
            content: html,
            css: {
                'padding': '20px',
                'max-width': '500px',
                'background-color': '#ffffff',
                'border': '1px solid #c8c8c8',
                'text-shadow': 'none'
            }
        });
    });
});
