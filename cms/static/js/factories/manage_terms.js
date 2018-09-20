define([
    'jquery', 'js/views/manage_terms'
], function($, ManageTermsView) {
    'use strict';
    return function(availableOrgs, getOrgTermsUrl, saveOrgTermUrl, removeOrgTermUrl) {
        var view = new ManageTermsView({
            el: $('.settings-details'),
            availableOrgs: availableOrgs,
            getOrgTermsUrl: getOrgTermsUrl,
            saveOrgTermUrl: saveOrgTermUrl,
            removeOrgTermUrl: removeOrgTermUrl
        });
        view.render();
    };
});
