/* eslint-disable no-underscore-dangle */
/* globals Logger, interpolate */

(function() {
    'use strict';

    this.Sequence = (function() {
        function Sequence(element) {
            var self = this;

            this.removeBookmarkIconFromActiveNavItem = function(event) {
                return Sequence.prototype.removeBookmarkIconFromActiveNavItem.apply(self, [event]);
            };
            this.addBookmarkIconToActiveNavItem = function(event) {
                return Sequence.prototype.addBookmarkIconToActiveNavItem.apply(self, [event]);
            };
            this._change_sequential = function(direction, event) {
                return Sequence.prototype._change_sequential.apply(self, [direction, event]);
            };
            this.selectPrevious = function(event) {
                return Sequence.prototype.selectPrevious.apply(self, [event]);
            };
            this.selectNext = function(event) {
                return Sequence.prototype.selectNext.apply(self, [event]);
            };
            this.goto = function(event) {
                return Sequence.prototype.goto.apply(self, [event]);
            };
            this.resizeHandler = function(event) {
                return Sequence.prototype.resizeHandler.apply(self, [event]);
            };
            this.toggleArrows = function() {
                return Sequence.prototype.toggleArrows.apply(self);
            };
            this.addToUpdatedProblems = function(problemId, newContentState, newState) {
                return Sequence.prototype.addToUpdatedProblems.apply(self, [problemId, newContentState, newState]);
            };
            this.hideTabTooltip = function(event) {
                return Sequence.prototype.hideTabTooltip.apply(self, [event]);
            };
            this.displayTabTooltip = function(event) {
                return Sequence.prototype.displayTabTooltip.apply(self, [event]);
            };
            this.detectScroll = function(event) {
                return Sequence.prototype.detectScroll.apply(self, [event]);
            };
            this.arrowKeys = {
                LEFT: 37,
                UP: 38,
                RIGHT: 39,
                DOWN: 40
            };

            this.updatedProblems = {};
            this.requestToken = $(element).data('request-token');
            this.el = $(element).find('.sequence');
            this.path = $('.path');
            this.contents = this.$('.seq_contents');
            this.content_container = this.$('#seq_content');
            this.sr_container = this.$('.sr-is-focusable');
            this.num_contents = this.contents.length;
            this.id = this.el.data('id');
            this.ajaxUrl = this.el.data('ajax-url');
            this.nextUrl = this.el.data('next-url');
            this.prevUrl = this.el.data('prev-url');
            this.savePosition = this.el.data('save-position');
            this.showCompletion = this.el.data('show-completion');

            this.graded = parseInt(this.el.data('graded')) === 1;
            this.showSummaryInfoAfterQuiz = parseInt(this.el.data('show-summary-info-after-quiz')) === 1;
            this.lmsUrlToGetGrades = this.el.data('lms-url-to-get-grades');
            this.lmsUrlToEmailGrades = this.el.data('lms-url-to-email-grades');
            this.scores = null;

            this.scoresBarTopPosition = null;
            this.courseNavBarMarginTop = null;

            this.returnToCourseOutline = parseInt(this.el.data('return-to-course-outline')) == 1;
            if (window.chromlessView) {
                this.returnToCourseOutline = false;
            }
            this.courseId = this.el.data('course-id');
            this.keydownHandler($(element).find('#sequence-list .tab'));
            this.base_page_title = ($('title').data('base-title') || '').trim();
            this.carouselView = false;
            if (this.$('.sequence-nav').hasClass("sequence-nav-carousel")) {
                this.carouselView = true;
            }
            this.resizeId = null;
            this.correctIcon = this.el.data('correct-icon');
            this.incorrectIcon = this.el.data('incorrect-icon');
            this.unansweredIcon = this.el.data('unanswered-icon');

            this.sequenceList = $(element).find('#sequence-list');
            this.widthElem = 170;
            this.carouselAllItemsLength = this.num_contents * this.widthElem;
            this.bind();

            var position = 0;
            var foundBlockId = false;
            var foundBlock = null;
            var search = window.location.search;
            var tmpArr = [];

            if (search) {
                var searchArr = search.substring(1).split('&');
                for (var i = 0; i < searchArr.length; i++) {
                    if (searchArr[i] && (searchArr[i].indexOf('activate_block_id') !== -1)) {
                        tmpArr = searchArr[i].split('=');
                        foundBlockId = decodeURIComponent(tmpArr[1]);
                        foundBlock = this.link_for_by_id(foundBlockId);
                        if (foundBlock.length > 0) {
                            position = foundBlock.data('element');
                        } else {
                            foundBlockId = false;
                        }
                    }
                }
            }
            if (!foundBlockId) {
                position = this.el.data('position');
            }

            if (this.supportDisplayResults()) {
                this.getQuestionsInfo();
            }

            this.render(parseInt(position, 10));
        }

        Sequence.prototype.showSendScoresPanel = function() {
            var panel = $('.scores-panel');
            var self = this;
            if ($(panel).hasClass('is-hidden')) {
                $(panel).html('<div class="exam-timer">' +
                    '<div class="exam-text">Click here to see details and email your score:' +
                    '<button class="get-scores-btn btn btn-pl-primary" href="#get-score-modal">Get Scores</button>' +
                    '<a href="#get-score-modal" class="get-scores-link" style="display: none;">Get Scores</a>' +
                    '</div>' +
                    '</div>');
                $(panel).removeClass('is-hidden');
                $(panel).show();

                $(panel).find('.get-scores-link').leanModal({
                    closeButton: '.close-modal',
                    top: 50
                });

                this.scoresBarTopPosition = $(panel).position().top;
                this.courseNavBarMarginTop = this.scoresBarTopPosition - 3;

                $(panel).find('.get-scores-btn').click(function () {
                    self.fetchAndDisplayResults();
                    $(panel).find('.get-scores-link').trigger('click');
                });

                this._checkScroll(window, this.scoresBarTopPosition, this.courseNavBarMarginTop);
                $(window).bind('scroll', this.detectScroll);
            }
        };

        Sequence.prototype.changeScoresBtn = function(enable) {
            var panel = $('.scores-panel');
            if (enable) {
                $(panel).find('.get-scores-btn').removeAttr('disabled').text('Get Scores');
            } else {
                $(panel).find('.get-scores-btn').attr('disabled', 'disabled').text('Please wait...');
            }
        };

        Sequence.prototype.detectScroll = function(event) {
            this._checkScroll(event.currentTarget, this.scoresBarTopPosition, this.courseNavBarMarginTop);
        };

        Sequence.prototype._checkScroll = function(target, scoresBarTopPosition, courseNavBarMarginTop) {
            if ($(target).scrollTop() > scoresBarTopPosition) {
                $(".scores-panel").addClass('is-fixed');
                $(".wrapper-course-material").css('margin-top', courseNavBarMarginTop + 'px');
            } else {
                $(".scores-panel").removeClass('is-fixed');
                $(".wrapper-course-material").css('margin-top', '0');
            }
        };

        Sequence.prototype.supportDisplayResults = function() {
            return this.graded && this.showSummaryInfoAfterQuiz;
        };

        Sequence.prototype.getQuestionsInfo = function() {
            var self = this;
            var showPanel = false;

            $.postWithPrefix(this.lmsUrlToGetGrades, {}, function(data) {
                if (!data.error) {
                    if (data.items.length > 0) {
                        $.each(data.items, function(idx, value) {
                            if (value.correctness !== 'Not Answered') {
                                showPanel = true;
                            }
                        });

                        if (showPanel) {
                            self.showSendScoresPanel();
                        }
                    }
                }
            });
        };

        Sequence.prototype.fetchAndDisplayResults = function() {
            var self = this;
            this.changeScoresBtn(false);

            this.$('.seq-grade-details-total-score-num').html('');
            this.$('.seq-grade-details-total-points-num').html('');
            this.$('.seq-grade-details-quiz-name').html('');
            this.$('.seq-grade-details-last-answer-timestamp').html('').hide();
            this.$('.seq-grade-details-items').html('');

            $.postWithPrefix(this.lmsUrlToGetGrades, {}, function(data) {
                self.changeScoresBtn(true);
                if ((!data.error) && (data.items.length > 0)) {
                    self.displayResults(data);
                }
            });
        };

        Sequence.prototype.validateEmail = function(email) {
            var re = /^(([^<>()\[\]\\.,;:\s@"]+(\.[^<>()\[\]\\.,;:\s@"]+)*)|(".+"))@((\[[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\])|(([a-zA-Z\-0-9]+\.)+[a-zA-Z]{2,}))$/;
            return re.test(String(email).toLowerCase());
        };

        Sequence.prototype.displayEmailError = function(msg) {
            this.$('.email-error').show().html(msg);
        };

        Sequence.prototype.lockSendEmailBtn = function() {
            this.$('.send-email-btn').attr('disabled', 'disabled');
            this.$('.send-email-btn').text('Sending...');
        };

        Sequence.prototype.unlockSendEmailBtn = function() {
            this.$('.send-email-btn').removeAttr('disabled');
            this.$('.send-email-btn').text('Send email');
        };

        Sequence.prototype.displayResults = function(data) {
            this.scores = data;

            this.$('.email-error').hide();
            this.$('.email-success').hide();

            var self = this;

            this.$('.seq-grade-details-total-score-num').html(this.scores.common.percent_graded + '%');
            this.$('.seq-grade-details-total-points-num').html(this.scores.common.earned + '/' + this.scores.common.possible);

            if (this.scores.common.last_answer_timestamp) {
                this.$('.seq-grade-details-last-answer-timestamp').show().html('Time of the last answer: ' + moment(this.scores.common.last_answer_timestamp).format("YYYY-MM-DD HH:mm"));
            } else {
                this.$('.seq-grade-details-last-answer-timestamp').hide();
            }

            this.$('.seq-grade-details-quiz-name').html(this.scores.common.quiz_name);

            var html = '';
            $.each(this.scores.items, function(idx, value) {
                var iconSrc = self.correctIcon;
                var iconWidth = 25;
                var iconHeight = 25;
                if (value.correctness === 'Not Answered') {
                    iconSrc = self.unansweredIcon;
                    iconWidth = 24;
                    iconHeight = 24;
                } else if (value.correctness === 'Incorrect') {
                    iconSrc = self.incorrectIcon;
                }
                html += '<div class="seq-grade-details-item-block"><table class="seq-grade-details-item-table"><tr>' +
                        '<td class="seq-grade-details-item-block-icon"><img src="' + iconSrc + '" alt="' + value.correctness + '" title="' + value.correctness + '" width="' + iconWidth + '" height="' + iconHeight + '" /></td>' +
                        '<td class="seq-grade-details-item-block-content">' +
                          '<div class="seq-grade-details-item-block-content-header">' + value.parent_name + ' <span class="icon fa fa-angle-right" aria-hidden="true"></span> ' + value.display_name + '</div>';
                if (value.last_answer_timestamp) {
                    html += '<div class="seq-grade-details-item-block-content-text">Time of the last answer: ' +
                            moment(value.last_answer_timestamp).format("YYYY-MM-DD HH:mm") +
                            '</div>';
                }
                if (value.question_text) {
                    html += '<div class="seq-grade-details-item-block-content-text">' + value.question_text + '</div>';
                }
                if (value.answer) {
                    html += '<div class="seq-grade-details-item-block-content-header">Answer</div>';
                    html += '<div class="seq-grade-details-item-block-content-text">' + value.answer + '</div>';
                }
                html += '</td>' +
                        '<td class="seq-grade-details-item-block-points">' + value.earned + '/' + value.possible + '</td>' +
                      '</tr></table></div>';
            });
            this.$('.seq-grade-details-items').html(html);

            this.$('.email-assessment').val('');
            if (this.scores.user.email) {
                this.$('.email-assessment').val(this.scores.user.email);
            }

            this.$('.send-email-btn').unbind('click');
            this.$('.send-email-btn').click(function(event) {
                var btn = $(this);
                event.preventDefault();

                var val = self.$('.email-assessment').val();
                var arr = val.split(',');
                var emailsArr = [];
                var isError = false;

                self.$('.email-error').hide();
                self.$('.email-success').hide();

                $.each(arr, function(index, value) {
                    if (isError) {
                        return;
                    }
                    var tmp = $.trim(value);
                    if (tmp != '') {
                        if (!self.validateEmail(tmp)) {
                            isError = true;
                            self.displayEmailError('Invalid email: ' + tmp);
                        } else {
                            emailsArr.push(tmp);
                        }
                    }
                });

                if (!isError) {
                    if (emailsArr.length > 0) {
                        self.lockSendEmailBtn();

                        var offset = new Date().getTimezoneOffset();

                        $.postWithPrefix(self.lmsUrlToEmailGrades, {
                            emails: emailsArr.join(','),
                            timezone_offset: (-1) * offset
                        }, function(data) {
                            btn.removeAttr('disabled');
                            btn.text('Email My Results');
                            if (data.success) {
                                self.$('.email-success').show();
                            } else {
                                self.displayEmailError(data.error);
                            }
                            self.unlockSendEmailBtn();
                        });
                    } else {
                        self.displayEmailError('Please enter at least one email');
                    }
                }
            });
        };

        Sequence.prototype.$ = function(selector) {
            return $(selector, this.el);
        };

        Sequence.prototype.bind = function() {
            if (this.carouselView) {
                this.$('#sequence-list .seq-item').click(this.goto);
                $(window).resize(this.resizeHandler);
            } else {
                this.$('#sequence-list .nav-item').click(this.goto);
            }
            this.$('#sequence-list .nav-item').keypress(this.keyDownHandler);
            this.el.on('bookmark:add', this.addBookmarkIconToActiveNavItem);
            this.el.on('bookmark:remove', this.removeBookmarkIconFromActiveNavItem);
            this.$('#sequence-list .nav-item').on('focus mouseenter', this.displayTabTooltip);
            this.$('#sequence-list .nav-item').on('blur mouseleave', this.hideTabTooltip);
        };

        Sequence.prototype.changeUrl = function(blockName, blockId) {
            blockName = blockName + ' | ' + this.base_page_title;
            blockId = encodeURIComponent(blockId);

            var pathname = window.location.pathname;
            var search = window.location.search;
            var newSearchArr = [];
            newSearchArr.push('activate_block_id=' + blockId);
            if (search) {
                var searchArr = search.substring(1).split('&');
                for (var i = 0; i < searchArr.length; i++) {
                    if (searchArr[i] && (searchArr[i].indexOf('activate_block_id') === -1)) {
                        newSearchArr.push(searchArr[i]);
                    }
                }
            }
            window.history.pushState({activate_block_id: blockId}, blockName, pathname + '?' + newSearchArr.join('&'));
        };

        Sequence.prototype.resizeHandler = function() {
            clearTimeout(this.resizeId);
            var self = this;
            this.resizeId = setTimeout(function() {
                self.highlightNewCarouselElem({
                    position: self.position,
                    animate: false});
            }, 500);
        };

        Sequence.prototype.highlightNewCarouselElem = function(options) {
            if (!this.carouselView) {
                return;
            }
            var position = options.position;
            var animate = options.animate;
            var x = position * this.widthElem;
            var carouselWidth = this.$('.sequence-list-wrapper').width();
            var currentMarginLeft = 0;

            if (animate) {
                currentMarginLeft = $(this.sequenceList).css('marginLeft').slice(0, -2);
                currentMarginLeft = (-1) * parseInt(currentMarginLeft, 10);
            }

            var len = currentMarginLeft + carouselWidth;
            var offset = 0;
            if (x < (currentMarginLeft + this.widthElem)) {
                offset = currentMarginLeft - x + this.widthElem;
                if (animate) {
                    $(this.sequenceList).animate({marginLeft: '+=' + offset});
                } else {
                    $(this.sequenceList).css({marginLeft: (-1) * offset});
                }
            } else if (x > len) {
                offset = x - len;
                if (animate) {
                    $(this.sequenceList).animate({marginLeft: '-=' + offset});
                } else {
                    $(this.sequenceList).css({marginLeft: (-1) * offset});
                }
            } else {
                if (!animate) {
                    $(this.sequenceList).css({marginLeft: 0});
                }
            }
        };

        Sequence.prototype.previousNav = function(focused, index) {
            var $navItemList,
                $sequenceList = $(focused).parent().parent();
            if (index === 0) {
                $navItemList = $sequenceList.find('li').last();
            } else {
                $navItemList = $sequenceList.find('li:eq(' + index + ')').prev();
            }
            $sequenceList.find('.tab').removeClass('visited').removeClass('focused');
            $navItemList.find('.tab').addClass('focused').focus();
        };

        Sequence.prototype.nextNav = function(focused, index, total) {
            var $navItemList,
                $sequenceList = $(focused).parent().parent();
            if (index === total) {
                $navItemList = $sequenceList.find('li').first();
            } else {
                $navItemList = $sequenceList.find('li:eq(' + index + ')').next();
            }
            $sequenceList.find('.tab').removeClass('visited').removeClass('focused');
            $navItemList.find('.tab').addClass('focused').focus();
        };

        Sequence.prototype.keydownHandler = function(element) {
            var self = this;
            element.keydown(function(event) {
                var key = event.keyCode,
                    $focused = $(event.currentTarget),
                    $sequenceList = $focused.parent().parent(),
                    index = $sequenceList.find('li')
                        .index($focused.parent()),
                    total = $sequenceList.find('li')
                        .size() - 1;
                switch (key) {
                case self.arrowKeys.LEFT:
                    event.preventDefault();
                    self.previousNav($focused, index);
                    break;

                case self.arrowKeys.RIGHT:
                    event.preventDefault();
                    self.nextNav($focused, index, total);
                    break;

                // no default
                }
            });
        };

        Sequence.prototype.displayTabTooltip = function(event) {
            $(event.currentTarget).find('.sequence-tooltip').removeClass('sr');
        };

        Sequence.prototype.hideTabTooltip = function(event) {
            $(event.currentTarget).find('.sequence-tooltip').addClass('sr');
        };

        Sequence.prototype.updatePageTitle = function() {
            // update the page title to include the current section
            var currentUnitTitle,
                newPageTitle,
                positionLink = this.link_for(this.position);

            if (positionLink && positionLink.data('page-title')) {
                currentUnitTitle = positionLink.data('page-title');
                newPageTitle = currentUnitTitle + ' | ' + this.base_page_title;

                if (newPageTitle !== document.title) {
                    document.title = newPageTitle;
                }

                // Update the title section of the breadcrumb
                $('.nav-item-sequence').text(currentUnitTitle);
            }
        };

        Sequence.prototype.hookUpContentStateChangeEvent = function() {
            var self = this;

            return $('.problems-wrapper').bind('contentChanged', function(event, problemId, newContentState, newState) {
                if (self.supportDisplayResults()) {
                    self.showSendScoresPanel();
                }
                return self.addToUpdatedProblems(problemId, newContentState, newState);
            });
        };

        Sequence.prototype.addToUpdatedProblems = function(problemId, newContentState, newState) {
            /**
            * Used to keep updated problem's state temporarily.
            * params:
            *   'problem_id' is problem id.
            *   'new_content_state' is the updated content of the problem.
            *   'new_state' is the updated state of the problem.
            */

            // initialize for the current sequence if there isn't any updated problem for this position.
            if (!this.anyUpdatedProblems(this.position)) {
                this.updatedProblems[this.position] = {};
            }

            // Now, put problem content and score against problem id for current active sequence.
            this.updatedProblems[this.position][problemId] = [newContentState, newState];
        };

        Sequence.prototype.anyUpdatedProblems = function(position) {
            /**
            * check for the updated problems for given sequence position.
            * params:
            *   'position' can be any sequence position.
            */
            return typeof(this.updatedProblems[position]) !== 'undefined';
        };

        Sequence.prototype.enableButton = function(buttonClass, buttonAction) {
            this.$(buttonClass)
                .removeClass('disabled')
                .removeAttr('disabled')
                .click(buttonAction);
        };

        Sequence.prototype.disableButton = function(buttonClass) {
            this.$(buttonClass).addClass('disabled').attr('disabled', true);
        };

        Sequence.prototype.updateButtonState = function(buttonClass, buttonAction, isAtBoundary, boundaryUrl) {
            if (!this.returnToCourseOutline && isAtBoundary && boundaryUrl === 'None') {
                this.disableButton(buttonClass);
            } else {
                this.enableButton(buttonClass, buttonAction);
            }
        };

        Sequence.prototype.toggleArrows = function() {
            var isFirstTab, isLastTab, nextButtonClass, previousButtonClass, previousCarouselButtonClass, nextCarouselButtonClass;

            this.$('.sequence-nav-button').unbind('click');
            this.$('.sequence-nav-button-carousel').unbind('click');

            // previous button
            isFirstTab = this.position === 1;
            previousButtonClass = '.sequence-nav-button.button-previous';
            this.updateButtonState(previousButtonClass, this.selectPrevious, isFirstTab, this.prevUrl);

            previousCarouselButtonClass = '.sequence-nav-button-carousel.button-previous-carousel';
            this.updateButtonState(previousCarouselButtonClass, this.selectPrevious, isFirstTab, this.prevUrl);

            // next button
            // use inequality in case contents.length is 0 and position is 1.
            isLastTab = this.position >= this.contents.length;
            nextButtonClass = '.sequence-nav-button.button-next';
            this.updateButtonState(nextButtonClass, this.selectNext, isLastTab, this.nextUrl);

            nextCarouselButtonClass = '.sequence-nav-button-carousel.button-next-carousel';
            this.updateButtonState(nextCarouselButtonClass, this.selectNext, isLastTab, this.nextUrl);
        };

        Sequence.prototype.render = function(newPosition) {
            var bookmarked, currentTab, modxFullUrl, sequenceLinks,
                self = this;
            this.highlightNewCarouselElem({
                position: newPosition,
                animate: true
            });
            if (this.position !== newPosition) {
                if (this.position) {
                    this.mark_visited(this.position);
                    if (this.showCompletion) {
                        this.update_completion(this.position);
                    }
                    if (this.savePosition) {
                        modxFullUrl = '' + this.ajaxUrl + '/goto_position';
                        $.postWithPrefix(modxFullUrl, {
                            position: newPosition
                        });
                    }
                }

                // clear video items that are ready to display
                window.videoReady = [];

                // On Sequence change, fire custom event 'sequence:change' on element.
                // Added for aborting video bufferization, see ../video/10_main.js
                this.el.trigger('sequence:change');
                this.mark_active(newPosition);
                currentTab = this.contents.eq(newPosition - 1);
                bookmarked = this.el.find('.active .bookmark-icon').hasClass('bookmarked');

                // update the data-attributes with latest contents only for updated problems.
                this.content_container
                    .html(currentTab.text())
                    .attr('aria-labelledby', currentTab.attr('aria-labelledby'))
                    .data('bookmarked', bookmarked);

                if (this.anyUpdatedProblems(newPosition)) {
                    $.each(this.updatedProblems[newPosition], function(problemId, latestData) {
                        var latestContent, latestResponse;
                        latestContent = latestData[0];
                        latestResponse = latestData[1];
                        self.content_container
                            .find("[data-problem-id='" + problemId + "']")
                            .data('content', latestContent)
                            .data('problem-score', latestResponse.current_score)
                            .data('problem-total-possible', latestResponse.total_possible)
                            .data('attempts-used', latestResponse.attempts_used);
                    });
                }
                XBlock.initializeBlocks(this.content_container, this.requestToken);

                // For embedded circuit simulator exercises in 6.002x
                if (window.hasOwnProperty('update_schematics')) {
                    window.update_schematics();
                }
                this.position = newPosition;
                this.toggleArrows();
                this.hookUpContentStateChangeEvent();
                this.updatePageTitle();
                sequenceLinks = this.content_container.find('a.seqnav');
                sequenceLinks.click(this.goto);

                this.sr_container.focus();

                // in case of switch tab
                // send to the parent frame information about new content width and height
                if (window.chromlessView && window.postMessageResize) {
                    window.postMessageResize();
                }
            }
        };

        Sequence.prototype.goto = function(event) {
            var alertTemplate, alertText, isBottomNav, newPosition, widgetPlacement;
            event.preventDefault();

            // Links from courseware <a class='seqnav' href='n'>...</a>, was .target_tab
            if ($(event.currentTarget).hasClass('seqnav')) {
                newPosition = $(event.currentTarget).attr('href');
            // Tab links generated by backend template
            } else {
                newPosition = $(event.currentTarget).data('element');
            }

            if ((newPosition >= 1) && (newPosition <= this.num_contents)) {
                isBottomNav = $(event.target).closest('nav[class="sequence-bottom"]').length > 0;

                if (isBottomNav) {
                    widgetPlacement = 'bottom';
                } else {
                    widgetPlacement = 'top';
                }

                // Formerly known as seq_goto
                Logger.log('edx.ui.lms.sequence.tab_selected', {
                    current_tab: this.position,
                    target_tab: newPosition,
                    tab_count: this.num_contents,
                    id: this.id,
                    widget_placement: widgetPlacement
                });

                // On Sequence change, destroy any existing polling thread
                // for queued submissions, see ../capa/display.js
                if (window.queuePollerID) {
                    window.clearTimeout(window.queuePollerID);
                    delete window.queuePollerID;
                }

                this.render(newPosition);

                if (!window.chromlessView) {
                    var positionLink = this.link_for(newPosition);
                    this.changeUrl(positionLink.data('page-title'), positionLink.data('id'));
                }
            } else {
                alertTemplate = gettext('Sequence error! Cannot navigate to %(tab_name)s in the current SequenceModule. Please contact the course staff.');  // eslint-disable-line max-len
                alertText = interpolate(alertTemplate, {
                    tab_name: newPosition
                }, true);
                alert(alertText);  // eslint-disable-line no-alert
            }
        };

        Sequence.prototype.selectNext = function(event) {
            this._change_sequential('next', event);
        };

        Sequence.prototype.selectPrevious = function(event) {
            this._change_sequential('previous', event);
        };

        // `direction` can be 'previous' or 'next'
        Sequence.prototype._change_sequential = function(direction, event) {
            var analyticsEventName, isBottomNav, newPosition, offset, targetUrl, widgetPlacement;

            // silently abort if direction is invalid.
            if (direction !== 'previous' && direction !== 'next') {
                return;
            }
            event.preventDefault();
            analyticsEventName = 'edx.ui.lms.sequence.' + direction + '_selected';
            isBottomNav = $(event.target).closest('nav[class="sequence-bottom"]').length > 0;

            if (isBottomNav) {
                widgetPlacement = 'bottom';
            } else {
                widgetPlacement = 'top';
            }

            if ((direction === 'next') && (this.position >= this.contents.length)) {
                if (this.returnToCourseOutline) {
                    targetUrl = '/courses/' + this.courseId + '/course/';
                } else {
                    targetUrl = this.nextUrl;
                }
            } else if ((direction === 'previous') && (this.position === 1)) {
                targetUrl = this.prevUrl;
            }

            // Formerly known as seq_next and seq_prev
            Logger.log(analyticsEventName, {
                id: this.id,
                current_tab: this.position,
                tab_count: this.num_contents,
                widget_placement: widgetPlacement
            }).always(function() {
                if (targetUrl) {
                    // Wait to load the new page until we've attempted to log the event
                    window.location.href = targetUrl;
                }
            });

            // If we're staying on the page, no need to wait for the event logging to finish
            if (!targetUrl) {
                // If the bottom nav is used, scroll to the top of the page on change.
                if (isBottomNav) {
                    $.scrollTo(0, 150);
                }

                offset = {
                    next: 1,
                    previous: -1
                };

                newPosition = this.position + offset[direction];
                this.render(newPosition);
            }
        };

        Sequence.prototype.link_for = function(position) {
            if (this.carouselView) {
                return this.$('#sequence-list .seq-item[data-element=' + position + ']');
            } else {
                return this.$('#sequence-list .nav-item[data-element=' + position + ']');
            }
        };

        Sequence.prototype.link_for_by_id = function(blockId) {
            if (this.carouselView) {
                return this.$('#sequence-list .seq-item[data-id="' + blockId + '"]');
            } else {
                return this.$('#sequence-list .nav-item[data-id="' + blockId + '"]');
            }
        };

        Sequence.prototype.mark_visited = function(position) {
            // Don't overwrite class attribute to avoid changing Progress class
            var element = this.link_for(position);
            element.attr({tabindex: '-1', 'aria-selected': 'false', 'aria-expanded': 'false'})
                .removeClass('inactive')
                .removeClass('active')
                .removeClass('focused')
                .addClass('visited');
        };

        Sequence.prototype.update_completion = function(position) {
            var element = this.link_for(position);
            var completionUrl = this.ajaxUrl + '/get_completion';
            var usageKey = element[0].attributes['data-id'].value;
            var completionIndicators = element.find('.check-circle');
            var supportCompletion = element.data('support-completion');
            if (this.carouselView) {
                supportCompletion = parseInt(supportCompletion, 10);
            }
            var self = this;
            if (completionIndicators.length || (supportCompletion === 1)) {
                $.postWithPrefix(completionUrl, {
                    usage_key: usageKey
                }, function(data) {
                    if (data.complete === true) {
                        if (self.carouselView) {
                            if (!$(element).hasClass('completed')) {
                                $(element).addClass('completed');
                            }
                        } else {
                            completionIndicators.removeClass('is-hidden');
                        }
                    }
                });
            }
        };

        Sequence.prototype.mark_active = function(position) {
            // Don't overwrite class attribute to avoid changing Progress class
            var element = this.link_for(position);
            element.attr({tabindex: '0', 'aria-selected': 'true', 'aria-expanded': 'true'})
                .removeClass('inactive')
                .removeClass('visited')
                .removeClass('focused')
                .addClass('active');
            this.$('.sequence-list-wrapper').focus();
        };

        Sequence.prototype.addBookmarkIconToActiveNavItem = function(event) {
            event.preventDefault();
            this.el.find('.nav-item.active .bookmark-icon').removeClass('is-hidden').addClass('bookmarked');
            this.el.find('.nav-item.active .bookmark-icon-sr').text(gettext('Bookmarked'));
        };

        Sequence.prototype.removeBookmarkIconFromActiveNavItem = function(event) {
            event.preventDefault();
            this.el.find('.nav-item.active .bookmark-icon').removeClass('bookmarked').addClass('is-hidden');
            this.el.find('.nav-item.active .bookmark-icon-sr').text('');
        };

        return Sequence;
    }());
}).call(this);
