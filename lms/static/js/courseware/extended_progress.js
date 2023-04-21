function getTooltipHtml(label, description, percentCorrect, value, total, coursesNum) {
    var displayTotal = ((total !== null) && (total !== undefined));
    var html = '<div class="tags-tooltip-block">' +
            ((description !== '') ? ('<div class="tags-description">' + description + '</div>') : '') +
            '<div class="tags-label">' + label + '</div>' +
            '<table class="tags-table">' +
            '<tr>' +
            '<td class="tags-percentage">' + percentCorrect + '%</td>' +
            '<td class="tags-percentage">' + (displayTotal ? (value + '/' + total) : value) + '</td>' +
            ((coursesNum > 0) ? ('<td class="tags-percentage">' + coursesNum + '</td>') : '') +
            '</tr>' +
            '<tr>' +
            '<td class="tags-help">Percent Correct</td>' +
            '<td class="tags-help">' + (displayTotal ? 'Correct/Total Questions' : 'Answers Submitted') + '</td>' +
            ((coursesNum > 0) ? ('<td class="tags-help">Courses</td>') : '') +
            '</tr>' +
            '</table>' +
            '</div>';
    return html;
}

function textTruncate(str, length, ending) {
    if (length == null) {
        length = 100;
    }
    if (ending == null) {
        ending = '...';
    }
    if (str.length > length) {
        return str.substring(0, length - ending.length) + ending;
    } else {
        return str;
    }
}

function formatChartLabel(str, maxwidth, truncate) {
    if (truncate !== 0) {
        str = textTruncate(str, truncate);
    }

    var sections = [];
    var words = str.split(" ");
    var temp = "";
    var item = "";

    for (var index = 0; index < words.length; index++) {
        item = words[index];
        if (temp.length > 0) {
            var concat = temp + ' ' + item;

            if (concat.length > maxwidth) {
                sections.push(temp);
                temp = "";
            } else {
                if (index === (words.length-1)) {
                    sections.push(concat);
                    continue;
                } else {
                    temp = concat;
                    continue;
                }
            }
        }

        if (index === (words.length-1)) {
            sections.push(item);
            continue;
        }

        if (item.length < maxwidth) {
            temp = item;
        } else {
            sections.push(item);
        }
    }

    return sections;
}

function displayAssessmentsChart(chartEl, passValue, data) {
    var dataValues = [];
    var backgroundColorValues = [];
    var labels = [];
    var labelMaxwidth = 30;
    var labelTruncate = 0;
    if ((data.length > 10) && (data.length <= 20)) {
        labelMaxwidth = 20;
        labelTruncate = 60;
    } else if (data.length > 20) {
        labelMaxwidth = 20;
        labelTruncate = 30;
    }

    for (var i = 0; i < data.length; i++) {
        dataValues.push(data[i].percent_correct);
        backgroundColorValues.push((data[i].percent_correct > passValue) ? 'rgba(0, 220, 255, 1)' : 'rgba(4, 109, 180, 1)');
        labels.push(formatChartLabel(data[i].title, labelMaxwidth, labelTruncate));
    }

    var datasets = {
        label: 'Percent Correct',
        data: dataValues,
        backgroundColor: backgroundColorValues
    };

    return new Chart(chartEl, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [datasets]
        },
        options: {
            legend: {
                display: false
            },
            scales: {
                xAxes: [{
                    ticks: {
                        autoSkip: false
                    },
                    gridLines: {
                        display: false,
                        color: 'rgb(99, 99, 99)'
                    }
                }],
                yAxes: [{
                    ticks: {
                        max: 100,
                        min: 0,
                        stepSize: passValue,
                        callback: function(value) {
                            return ((value === passValue) ? ('Pass ' + passValue) : value) + '%';
                        }
                    },
                    gridLines: {
                        display: false,
                        color: 'rgb(99, 99, 99)'
                    }
                }]
            },
            tooltips: {
                // Disable the on-canvas tooltip
                enabled: false,

                custom: function(tooltipModel) {
                    // Tooltip Element
                    var tooltipEl = document.getElementById('chartjs-tooltip');

                    // Create element on first render
                    if (!tooltipEl) {
                        tooltipEl = document.createElement('div');
                        tooltipEl.id = 'chartjs-tooltip';
                        tooltipEl.innerHTML = "<div class='progress-tooltip'></div>";
                        document.body.appendChild(tooltipEl);
                    }

                    // Hide if no tooltip
                    if (tooltipModel.opacity === 0) {
                        tooltipEl.style.opacity = 0;
                        return;
                    }

                    // Set caret Position
                    tooltipEl.classList.remove('above', 'below', 'no-transform');
                    if (tooltipModel.yAlign) {
                        tooltipEl.classList.add(tooltipModel.yAlign);
                    } else {
                        tooltipEl.classList.add('no-transform');
                    }

                    // Set Text
                    if (tooltipModel.body) {
                        var idx = tooltipModel.dataPoints[0].index;
                        var val = data[idx];
                        var tableRoot = tooltipEl.querySelector('.progress-tooltip');
                        var html = getTooltipHtml(val.title, '', val.percent_correct, val.correct,
                          val.total, 0);
                        tableRoot.innerHTML = '<div style="background-color: #ffffff; ' +
                            'border: 1px solid #c8c8c8; ' +
                            'max-width: 500px; ' +
                            'padding: 20px;">' + html + '</div>';
                    }

                    // `this` will be the overall tooltip
                    var position = this._chart.canvas.getBoundingClientRect();

                    // Display, position, and set styles for font
                    tooltipEl.style.opacity = 1;
                    tooltipEl.style.position = 'absolute';
                    tooltipEl.style.left = position.left + window.pageXOffset + tooltipModel.caretX + 'px';
                    tooltipEl.style.top = position.top + window.pageYOffset + tooltipModel.caretY + 'px';
                    tooltipEl.style.fontFamily = tooltipModel._bodyFontFamily;
                    tooltipEl.style.fontSize = tooltipModel.bodyFontSize + 'px';
                    tooltipEl.style.fontStyle = tooltipModel._bodyFontStyle;
                    tooltipEl.style.padding = tooltipModel.yPadding + 'px ' + tooltipModel.xPadding + 'px';
                    tooltipEl.style.pointerEvents = 'none';
                }
            },
            annotation: {
                annotations: [{
                    type: 'line',
                    mode: 'horizontal',
                    scaleID: 'y-axis-0',
                    value: passValue,
                    borderColor: 'rgb(99, 99, 99)',
                    borderWidth: 0,
                    label: {
                        enabled: false
                    }
                }]
            }
        }
    });
}

function displayAssessmentsTree() {
    var currentOrderBy = $('.progress-assessments-body').data('current-order-by');
    var currentSort = -1;

    $('.progress-assessments-expand-link').live("click", function() {
        var blockType = $(this).data('block-type');
        var loaded = parseInt($(this).attr('data-loaded'));
        var opened = $(this).hasClass('opened');
        var parent = null;
        var contentEl = null;
        var postParams = null;
        var dataApiUrl = '';
        var self = this;

        if (opened) {
            $(this).removeClass('opened');
            $(this).find('.header-icon').removeClass('fa-chevron-down').addClass('fa-chevron-right');

            if (blockType === 'assessments') {
                parent = $(this).closest(".progress-tags-assessments-item");
                $(parent).find('.progress-tags-assessments-item-assessments').addClass('closed');
            } else if (blockType === 'questions') {
                parent = $(this).closest(".progress-tags-assessments-item-assessment");
                $(parent).find('.progress-tags-assessments-item-assessment-questions').addClass('closed');
            }
        } else {
            $(this).addClass('opened');
            $(this).find('.header-icon').removeClass('fa-chevron-right').addClass('fa-chevron-down');

            if (blockType === 'assessments') {
                parent = $(this).closest(".progress-tags-assessments-item");
                contentEl = $(parent).find('.progress-tags-assessments-item-assessments');
                contentEl.removeClass('closed');
            } else if (blockType === 'questions') {
                parent = $(this).closest(".progress-tags-assessments-item-assessment");
                contentEl = $(parent).find('.progress-tags-assessments-item-assessment-questions');
                contentEl.removeClass('closed');
            }

            if ((loaded === 0) && contentEl) {
                postParams = {
                    "student_id": window.extendedProgressAPI.api_student_id,
                    "org": window.extendedProgressAPI.api_org
                };
                if (blockType === 'assessments') {
                    dataApiUrl = window.extendedProgressAPI.urlApiGetTagData;
                    postParams['tag'] = $(this).data('tag-title');
                } else if (blockType === 'questions') {
                    dataApiUrl = window.extendedProgressAPI.urlApiGetTagSectionData;
                    postParams['tag'] = $(this).data('tag-title');
                    postParams['section_id'] = $(this).data('section-id');
                }

                if (dataApiUrl) {
                    contentEl.html('<div style="padding: 20px 0px 20px 0px;">Loading...</div>');

                    $.ajax({
                        url: dataApiUrl,
                        type: 'POST',
                        data: postParams,
                        dataType: "html",
                        success: function(res) {
                            contentEl.html(res);
                            $(self).attr("data-loaded", "1");
                        }
                    });
                }
            }
        }
    });

    $('.progress-assessments-cell-head-link').click(function() {
        var itemOrderBy = $(this).data('order-by');
        var itemOrderByType = $(this).data('order-by-type');
        if (itemOrderBy === currentOrderBy) {
            currentSort = currentSort * (-1);
        } else {
            currentOrderBy = itemOrderBy;
            currentSort = 1;
        }
        var sortIcon = '';
        if (currentSort === 1) {
            sortIcon = '<i class="fa fa-chevron-up header-icon progress-assessments-cell-head-icon" aria-hidden="true"></i>';
        } else {
            sortIcon = '<i class="fa fa-chevron-down header-icon progress-assessments-cell-head-icon" aria-hidden="true"></i>';
        }

        $('.progress-assessments-cell-head-icon').remove();
        var link = $('.progress-assessments-cell-head-link-' + currentOrderBy);
        link.html(link.html() + sortIcon);

        var mainDiv = $('.progress-assessments-body');
        var items = mainDiv.find('.progress-tags-assessments-item').get();

        items.sort(function (a, b) {
            var valA = $(a).data(currentOrderBy);
            var valB = $(b).data(currentOrderBy);
            if (itemOrderByType === 'int') {
                valA = parseInt(valA);
                valB = parseInt(valB);
            }

            if (currentSort === -1) {
                return (valA > valB) ? -1 : (valA < valB) ? 1 : 0;
            } else if (currentSort === 1) {
                return (valA < valB) ? -1 : (valA > valB) ? 1 : 0;
            }
        });

        $.each(items, function(index, row) {
            mainDiv.append(row);
        });
    });
}

$(document).ready(function() {
    displayAssessmentsTree();

    $('.tags-block-info-data').each(function() {
        var label = $(this).data('label'),
            percentCorrect = $(this).data('percent-correct'),
            answers = $(this).data('answers'),
            description = $(this).data('description'),
            coursesNum = parseInt($(this).data('courses-num'));
        $(this).tooltipsy({
            alignTo: 'cursor',
            offset: [0, 1],
            delay: 200,
            content: getTooltipHtml(label, description, percentCorrect, answers, null, coursesNum),
            css: {
                'padding': '20px',
                'max-width': '500px',
                'background-color': '#ffffff',
                'border': '1px solid #c8c8c8',
                'text-shadow': 'none'
            }
        });
    });

    $(".tags-block-clickable").click(function() {
        var tableNested = $(this).parent().find('.tags-table-nested').first();
        if (tableNested.length > 0) {
            if ($(this).hasClass('opened')) {
                tableNested.hide();
                $(this).removeClass('opened');
                $(this).find('.fa-chevron-down').removeClass('fa-chevron-down').addClass('fa-chevron-right');
            } else {
                tableNested.show();
                $(this).addClass('opened');
                $(this).find('.fa-chevron-right').removeClass('fa-chevron-right').addClass('fa-chevron-down');
            }
        }
    });

    $(".tags-block-see-all-link").click(function() {
        $(".tags-all-skills-menu").addClass('tags-all-skills-menu-show');
    });

    function sortRows(elem, sortBy) {
        var rows;
        elem.find('> tbody > tr > td > .tags-table-main').each(function() {
            sortRows($(this), sortBy);
        });

        rows = elem.find('> tbody > tr').get();
        rows.sort(function (a, b) {
            var contentApc = parseInt($(a).data('percent-correct'));
            var contentAl = $(a).data('label');
            var contentBpc = parseInt($(b).data('percent-correct'));
            var contentBl = $(b).data('label');

            if (sortBy === 'h2l') {
                return (contentApc > contentBpc) ? -1 : (contentApc < contentBpc) ? 1 : 0;
            } else if (sortBy === 'l2h') {
                return (contentApc < contentBpc) ? -1 : (contentApc > contentBpc) ? 1 : 0;
            } else if (sortBy === 'a2z') {
                return (contentAl < contentBl) ? -1 : (contentAl > contentBl) ? 1 : 0;
            } else if (sortBy === 'z2a') {
                return (contentAl > contentBl) ? -1 : (contentAl < contentBl) ? 1 : 0;
            }
        });

        $.each(rows, function(index, row) {
            elem.append(row);
        });
    }

    $(".tags-sort-link").on("click", function() {
        var sortBy = $(this).data('sort-by');
        var table = $('.tags-table-main').first();
        sortRows(table, sortBy);
    });

    if ($(".tags-sort-link").length > 0) {
        document.addEventListener('click', function(event) {
            if (!$(event.target).hasClass('tags-block-see-all-part')) {
                $(".tags-all-skills-menu").removeClass('tags-all-skills-menu-show');
            }
        });
    }

    var chartEl = document.getElementById("assessmentsChart");
    if (chartEl && window.extendedProgressChart) {
        displayAssessmentsChart(chartEl, window.extendedProgressChart.passValue, window.extendedProgressChart.data);
    }

    $('.print-progress-page').click(function() {
        window.print();
    });
});
