/**
 * Track interaction with the student dashboard..
 */

var edx = edx || {};

(function ($) {
    'use strict';

    edx.dashboard = edx.dashboard || {};

    edx.dashboard.TrackEvents = function() {

        // Emit an event when the "course title link" is clicked.
        $(".course-title-link").on("click", function (event) {
            var courseKey = $(event.target).data("course-key");
            window.analytics.track(
                "edx.bi.dashboard.course_title.clicked",
                {
                    category: "dashboard",
                    label: courseKey
                }
            );
        });

        // Emit an event  when the "course image" is clicked.
        $(".dashboard-course-image").on("click", function (event) {
            var courseKey = $(event.target).closest(".dashboard-course-image").data("course-key");
            window.analytics.track(
                "edx.bi.dashboard.course_image.clicked",
                {
                    category: "dashboard",
                    label: courseKey
                }
            );
        });

        // Emit an event  when the "View Course" button is clicked.
        $(".enter-course-link").on("click", function (event) {
            var courseKey = $(event.target).data("course-key");
            window.analytics.track(
                "edx.bi.dashboard.enter_course.clicked",
                {
                    category: "dashboard",
                    label: courseKey
                }
            );
        });

        // Emit an event when the options dropdown is engaged.
        $(".wrapper-action-more").on("click", function (event) {
            var courseKey = $(event.target).closest(".wrapper-action-more").data("course-key");
            window.analytics.track(
                "edx.bi.dashboard.more_action_button.clicked",
                {
                    category: "dashboard",
                    label: courseKey
                }
            );
        });

        // Emit an event  when the "Learn about verified" link is clicked.
        $(".verified-info").on("click", function (event) {
            var courseKey = $(event.target).data("course-key");
            window.analytics.track(
                "edx.bi.dashboard.learn_verified.clicked",
                {
                    category: "dashboard",
                    label: courseKey
                }
            );
        });

        // Emit an event  when the "Find Courses" button is clicked.
        $(".btn-find-courses").on("click", function () {
            window.analytics.track(
                "edx.bi.dashboard.find_course_button.clicked",
                {
                    category: "dashboard",
                    label: "find_course_button"
                }
            );
        });
    };

    $(document).ready(function() {

        edx.dashboard.TrackEvents();

    });
})(jQuery);
