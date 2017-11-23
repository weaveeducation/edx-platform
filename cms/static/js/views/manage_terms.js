define(['jquery', 'jquery.ui', 'js/views/baseview', 'common/js/components/views/feedback_prompt', 'moment'],
        function($, ui, BaseView, PromptView, moment) {
            var ManageTermsView = BaseView.extend({
                initialize: function(options) {
                    this.$el.find('.main-block').show();
                    this.selectedOrg = null;
                    this.currentOrgTerms = [];
                    this.getOrgTermsUrl = options.getOrgTermsUrl;
                    this.saveOrgTermUrl = options.saveOrgTermUrl;
                    this.removeOrgTermUrl = options.removeOrgTermUrl;

                    if (options.availableOrgs.length > 1) {
                        var d = $("<div></div>");
                        var s = $("<select id=\"orgSelector\" name=\"orgSelector\" />");
                        s.on("change", $.proxy(this, "changeOrg"));
                        var opts = [];
                        var self = this;
                        $.each(options.availableOrgs, function(index, value) {
                            var tmp = {value: value, text: value};
                            if (index === 0) {
                                self.selectedOrg = value;
                                tmp.selected = 'selected';
                            }
                            opts.push($("<option />", tmp));
                        });
                        s.append(opts);
                        d.append($('<h2>Please select Organization:</h2>'));
                        d.append(s);
                        this.$el.find('#orgSelectorBlock').append(d);
                    } else if (options.availableOrgs.length === 1) {
                        this.$el.find('.main-block').show();
                        this.selectedOrg = options.availableOrgs[0];
                    } else {
                        this.$el.find('.no-courses').show();
                    }
                },

                blockInterface: function() {
                    this.$el.find('#orgSelector').attr('disabled', 'disabled');
                    this.$el.find('button').attr('disabled', 'disabled');
                },

                unblockInterface: function() {
                    this.$el.find('#orgSelector').removeAttr('disabled');
                    this.$el.find('button').removeAttr('disabled');
                },

                getItemTpl: function() {
                    return '<li class="field-group field-group-course-start block-%id"> \
                          <div class="field"> \
                            <div>%title</div> \
                          </div> \
                          <div class="field field-date"> \
                            <div>%startDate</div> \
                          </div> \
                          <div class="field field-date"> \
                            <div>%endDate</div> \
                          </div> \
                          <div class="field"> \
                            <button type="button" class="edit-item-%id" data-id="%id">Edit</button>&nbsp; \
                            <button type="button" class="remove-item-%id" data-id="%id">Remove</button> \
                          </div> \
                        </li>';
                },

                getEditItemTpl: function(showCancel) {
                    var tplCancel = '';
                    if (showCancel) {
                        tplCancel = '<button type="button" class="cancel-item-%id" data-id="%id">Cancel</button>&nbsp;';
                    }
                    return '<li class="field-group field-group-course-start block-%id"> \
                          <div class="field"> \
                            <input type="text" value="%title" id="title-%id" maxlength="20" autocomplete="off" > \
                          </div> \
                          <div class="field field-date"> \
                            <input type="text" id="start-date-%id" class="start-date date"\
                                   placeholder="MM/DD/YYYY" autocomplete="off" value="%startDate"> \
                          </div> \
                          <div class="field field-date"> \
                            <input type="text" id="end-date-%id" class="end-date date"\
                                   placeholder="MM/DD/YYYY" autocomplete="off" value="%endDate"> \
                          </div> \
                          <div class="field"> \
                            ' + tplCancel + '<button type="button" class="save-item-%id" data-id="%id">Save</button> \
                          </div> \
                          <div class="error-msg error-msg-%id"></div> \
                        </li>';
                },

                fetchOrgTerms: function(onSuccess) {
                    var self = this;
                    this.$el.find('.loading').show();
                    $.ajax({
                        type: 'GET',
                        url: this.getOrgTermsUrl + this.selectedOrg,
                        contentType: 'application/json',
                        dataType : "json"
                    }).success(function(response) {
                        self.currentOrgTerms = [];
                        if (response.success) {
                            $.each(response.data, function(index, value) {
                                self.currentOrgTerms.push({
                                    id: value.id,
                                    title: value.term,
                                    startDate: value.start_date,
                                    endDate: value.end_date
                                });
                            });
                            onSuccess();
                        }
                    }).error(function() {
                        self.currentOrgTerms = [];
                    }).complete(function() {
                        self.$el.find('.loading').hide();
                    });
                },

                getOrgTerm: function(id) {
                    id = parseInt(id);
                    var item = null;
                    $.each(this.currentOrgTerms, function(index, value) {
                        if (value.id === id) {
                            item = value;
                        }
                    });
                    return item;
                },

                addToStorage: function(newItem) {
                    this.currentOrgTerms.push(newItem);
                },

                updateStorage: function(newItem) {
                    var newTerms = [];
                    $.each(this.currentOrgTerms, function(idx, value) {
                        if (value.id !== newItem.id) {
                            newTerms.push(value);
                        } else {
                            newTerms.push(newItem);
                        }
                    });
                    this.currentOrgTerms = newTerms;
                },

                removeFromStorage: function(id) {
                    id = parseInt(id);
                    var newTerms = [];
                    $.each(this.currentOrgTerms, function(index, value) {
                        if (value.id !== id) {
                            newTerms.push(value);
                        }
                    });
                    this.currentOrgTerms = newTerms;
                },

                showTermLine: function(replaceId, editMode, value) {
                    var tpl = '';
                    if (editMode) {
                        tpl = this.getEditItemTpl(replaceId !== null && editMode);
                    } else {
                        tpl = this.getItemTpl();
                    }

                    tpl = tpl.replace(/%title/g, value.title)
                             .replace(/%startDate/g, value.startDate)
                             .replace(/%endDate/g, value.endDate)
                             .replace(/%id/g, value.id);

                    if (replaceId === null) {
                        this.$el.find('.list-terms').append(tpl);
                    } else {
                        this.$el.find('.block-' + replaceId).replaceWith(tpl);
                    }

                    if (editMode) {
                        this.$el.find('#start-date-' + value.id).datepicker({'dateFormat': 'm/d/yy'});
                        this.$el.find('#end-date-' + value.id).datepicker({'dateFormat': 'm/d/yy'});
                        this.$el.find('.save-item-' + value.id).on("click", $.proxy(this, "saveTerm"));
                        if (replaceId !== null) {
                            this.$el.find('.cancel-item-' + value.id).on("click", $.proxy(this, "cancelTerm"));
                        }
                    } else {
                        this.$el.find('.edit-item-' + value.id).on("click", $.proxy(this, "editTerm"));
                        this.$el.find('.remove-item-' + value.id).on("click", $.proxy(this, "removeTerm"));
                    }
                },

                showTermsBlock: function() {
                    this.$el.find('.list-terms').empty();
                    var self = this;
                    this.fetchOrgTerms(function() {
                        $.each(self.currentOrgTerms, function(index, value) {
                            self.showTermLine(null, false, value);
                        });
                        if (self.selectedOrg) {
                            self.addCreateBlock();
                        }
                    });
                },

                changeOrg: function(e) {
                    this.selectedOrg = $(e.currentTarget).val();
                    this.showTermsBlock();
                },

                editTerm: function(e) {
                    var id = parseInt($(e.currentTarget).data('id'));
                    var item = this.getOrgTerm(id);
                    this.showTermLine(id, true, item);
                },

                removeTerm: function(e) {
                    var id = parseInt($(e.currentTarget).data('id'));
                    var item = this.getOrgTerm(id);
                    var self = this;

                    var confirm = new PromptView.Warning({
                        title: gettext('Are you sure you want to delete this term: ' + item.title + ' ?'),
                        message: gettext('This action cannot be undone.'),
                        actions: {
                            primary: {
                                text: gettext('OK'),
                                click: function() {
                                    self.$el.find('.remove-item-' + id).text("Removing...");
                                    self.blockInterface();
                                    $.ajax({
                                        type: 'POST',
                                        url: self.removeOrgTermUrl + self.selectedOrg,
                                        contentType: 'application/json',
                                        dataType : "json",
                                        data: JSON.stringify({
                                            id: id
                                        })
                                    }).success(function(response) {
                                        if (response.success) {
                                            self.$el.find('.block-' + id).remove();
                                            self.removeFromStorage(id);
                                        } else {
                                            self.$el.find('.remove-item-' + id).text("Remove");
                                        }
                                    }).error(function (xhr) {
                                        self.$el.find('.remove-item-' + id).text("Remove");
                                    }).complete(function() {
                                        self.unblockInterface();
                                    });
                                    confirm.hide();
                                }
                            },
                            secondary: {
                                text: gettext('Cancel'),
                                click: function() {
                                    confirm.hide();
                                }
                            }
                        }
                    });
                    confirm.show();
                },

                saveTerm: function(e) {
                    var id = $(e.currentTarget).data('id').toString();
                    var title = this.$el.find('#title-' + id).val();
                    var startDate = this.$el.find('#start-date-' + id).val();
                    var endDate = this.$el.find('#end-date-' + id).val();
                    var isNew = id.indexOf('new') === 0;
                    var self = this;

                    this.showErrorMessage(id, "");

                    if (!title) {
                        this.showErrorMessage(id, "Title field can't be empty");
                        return false;
                    }

                    if (!startDate) {
                        this.showErrorMessage(id, "Start Date field can't be empty");
                        return false;
                    }

                    if (!endDate) {
                        this.showErrorMessage(id, "End Date field can't be empty");
                        return false;
                    }

                    var d1Arr = startDate.split('/');
                    var d1 = new Date(d1Arr[2], d1Arr[0] - 1, d1Arr[1]);
                    var d2Arr = endDate.split('/');
                    var d2 = new Date(d2Arr[2], d2Arr[0] - 1, d2Arr[1]);

                    var isAfter = moment(d2).isAfter(d1);
                    if (!isAfter) {
                        this.showErrorMessage(id, "End Date must be after the Start Date");
                        return false;
                    }

                    this.$el.find('.save-item-' + id).text("Saving...");

                    var item = {
                        'title': title,
                        'startDate': startDate,
                        'endDate': endDate
                    };

                    if (!isNew) {
                        item.id = id;
                    }

                    this.blockInterface();

                    $.ajax({
                        type: 'POST',
                        url: this.saveOrgTermUrl + this.selectedOrg,
                        contentType: 'application/json',
                        dataType : "json",
                        data: JSON.stringify(item)
                    }).success(function(response) {
                        if (response.success) {
                            if (isNew) {
                                item.id = response.term.id;
                                self.addToStorage(item);
                                self.addCreateBlock();
                            } else {
                                self.updateStorage(item);
                            }
                            self.showTermLine(id, false, item);
                        } else {
                            self.showErrorMessage(id, response.errorMessage);
                            self.$el.find('.save-item-' + id).text("Save");
                        }
                    }).error(function (xhr) {
                        self.$el.find('.save-item-' + id).text("Save");
                    }).complete(function() {
                        self.unblockInterface();
                    });
                },

                showErrorMessage: function(id, text) {
                    this.$el.find('.error-msg-' + id).html(text);
                },

                cancelTerm: function(e) {
                    var id = parseInt($(e.currentTarget).data('id'));
                    var item = this.getOrgTerm(id);
                    this.showTermLine(id, false, item);
                },

                addCreateBlock: function() {
                    this.showTermLine(null, true, {
                        title: '',
                        startDate: '',
                        endDate: '',
                        id: 'new' + Date.now()
                    });
                },

                render: function() {
                    this.showTermsBlock();
                }
           });

           return ManageTermsView;
       });
