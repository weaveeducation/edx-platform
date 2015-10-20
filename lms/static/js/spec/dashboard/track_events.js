define([
        'jquery',
        'js/dashboard/track_events'
    ],
    function($) {
        'use strict';

        describe("edx.dashboard.TrackEvents", function() {

            var COURSE_ID = "edX/DemoX/Demo_Course";
            var CATEGORY = "dashboard";

            beforeEach(function() {
                // Stub the analytics event tracker
                window.analytics = jasmine.createSpyObj('analytics', ['track']);
                loadFixtures('js/fixtures/dashboard/dashboard.html');
                window.edx.dashboard.TrackEvents();
            });

            it("sends an analytics event when the user clicks course title link", function() {
                $(".course-title-link").click();
                // Verify that analytics events fire when the "course title link" is clicked.
                expect(window.analytics.track).toHaveBeenCalledWith(
                    "edx.bi.dashboard.course_title.clicked",
                    {
                        category: CATEGORY,
                        label: COURSE_ID
                    }
                );
            });

            it("sends an analytics event when the user clicks course image link", function() {
                $(".dashboard-course-image").click();
                // Verify that analytics events fire when the "course image link" is clicked.
                expect(window.analytics.track).toHaveBeenCalledWith(
                    "edx.bi.dashboard.course_image.clicked",
                    {
                        category: CATEGORY,
                        label: COURSE_ID
                    }
                );
            });


            it("sends an analytics event when the user clicks enter course link", function() {
                $(".enter-course-link").click();
                // Verify that analytics events fire when the "enter course link" is clicked.
                expect(window.analytics.track).toHaveBeenCalledWith(
                    "edx.bi.dashboard.enter_course.clicked",
                    {
                        category: CATEGORY,
                        label: COURSE_ID
                    }
                );
            });

            it("sends an analytics event when the user clicks enter course link", function() {
                $(".wrapper-action-more").click();
                // Verify that analytics events fire when the "Settings" button is clicked.
                expect(window.analytics.track).toHaveBeenCalledWith(
                    "edx.bi.dashboard.more_action_button.clicked",
                    {
                        category: CATEGORY,
                        label: COURSE_ID
                    }
                );
            });

            it("sends an analytics event when the user clicks the learned about verified track link", function() {
                $(".verified-info").click();
                //Verify that analytics events fire when the "Learned about verified track" link is clicked.
                expect(window.analytics.track).toHaveBeenCalledWith(
                    "edx.bi.dashboard.learn_verified.clicked",
                    {
                        category: CATEGORY,
                        label: COURSE_ID
                    }
                );
            });

            it("sends an analytics event when the user clicks find courses button", function() {
                $(".btn-find-courses").click();
                // Verify that analytics events fire when the "user clicks find the course" button.
                expect(window.analytics.track).toHaveBeenCalledWith(
                    "edx.bi.dashboard.find_course_button.clicked",
                    {
                        category: CATEGORY,
                        label: 'find_course_button'
                    }
                );
            });
        });
    }
);
