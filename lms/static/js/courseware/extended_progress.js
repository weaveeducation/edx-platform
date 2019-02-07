function getTooltipHtml(label, percentCorrect, answers, total) {
    var displayTotal = ((total !== null) && (total !== undefined));
    var html = '<div class="tags-tooltip-block">' +
            '<div class="tags-label">' + label + '</div>' +
            '<table class="tags-table">' +
            '<tr>' +
            '<td class="tags-percentage">' + percentCorrect + '%</td>' +
            '<td class="tags-percentage">' + (displayTotal ? (answers + '/' + total) : answers) + '</td>' +
            '</tr>' +
            '<tr>' +
            '<td class="tags-help">Percent Correct</td>' +
            '<td class="tags-help">' + (displayTotal ? 'Submitted/Total Answers' : 'Answers Submitted') + '</td>' +
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
        dataValues.push(data[i].value);
        backgroundColorValues.push((data[i].value > passValue) ? 'rgba(0, 220, 255, 1)' : 'rgba(4, 109, 180, 1)');
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
                        var html = getTooltipHtml(val.title, val.value, val.submitted, val.total);
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
                        enabled: false,
                    }
                }]
            }
        }
    });
}

$(document).ready(function() {
    $('.tags-block-info-data').each(function() {
        var label = $(this).data('label'),
            percentCorrect = $(this).data('percent-correct'),
            answers = $(this).data('answers');
        $(this).tooltipsy({
            alignTo: 'cursor',
            offset: [0, 1],
            delay: 0,
            content: getTooltipHtml(label, percentCorrect, answers, null),
            css: {
                'padding': '20px',
                'max-width': '500px',
                'background-color': '#ffffff',
                'border': '1px solid #c8c8c8',
                'text-shadow': 'none'
            }
        });
    });

    var chartEl = document.getElementById("assessmentsChart");
    if (chartEl && window.extendedProgressChart) {
        displayAssessmentsChart(chartEl, window.extendedProgressChart.passValue, window.extendedProgressChart.data);
    }
});
