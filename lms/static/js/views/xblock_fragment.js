(function($, _, Backbone, require) {
    var XBlockFragment = Backbone.View.extend({
        /**
         * Renders an xblock fragment into the specified element. The fragment has two attributes:
         *   html: the HTML to be rendered
         *   resources: any JavaScript or CSS resources that the HTML depends upon
         * Note that the XBlock is rendered asynchronously, and so a promise is returned that
         * represents this process.
         * @param fragment The fragment returned from the xblock_handler
         * @param element The element into which to render the fragment (defaults to this.$el)
         * @returns {Promise} A promise representing the rendering process
         */
        render: function(fragment, element) {
            var html = fragment.html,
                resources = fragment.resources;
            if (!element) {
                element = this.$el;
            }

            // Render the HTML first as the scripts might depend upon it, and then
            // asynchronously add the resources to the page. Any errors that are thrown
            // by included scripts are logged to the console but are then ignored assuming
            // that at least the rendered HTML will be in place.
            try {
                this.updateHtml(element, html);
                return this.addXBlockFragmentResources(resources);
            } catch (e) {
                console.error(e.stack);
                return $.Deferred().resolve();
            }
        },

        /**
         * Updates an element to have the specified HTML. The default method sets the HTML
         * as child content, but this can be overridden.
         * @param element The element to be updated
         * @param html The desired HTML.
         */
        updateHtml: function(element, html) {
            element.html(html);
        },

        /**
         * Dynamically loads all of an XBlock's dependent resources. This is an asynchronous
         * process so a promise is returned.
         * @param resources The resources to be rendered
         * @returns {Promise} A promise representing the rendering process
         */
        addXBlockFragmentResources: function(resources) {
            var self = this,
                applyResource,
                numResources,
                deferred;
            numResources = resources.length;
            deferred = $.Deferred();
            applyResource = function(index) {
                var hash, resource, value, promise;
                if (index >= numResources) {
                    deferred.resolve();
                    return;
                }
                value = resources[index];
                hash = value[0];
                if (!window.loadedXBlockResources) {
                    window.loadedXBlockResources = [];
                }
                if (_.indexOf(window.loadedXBlockResources, hash) < 0) {
                    resource = value[1];
                    promise = self.loadResource(resource);
                    window.loadedXBlockResources.push(hash);
                    promise.done(function() {
                        applyResource(index + 1);
                    }).fail(function() {
                        deferred.reject();
                    });
                } else {
                    applyResource(index + 1);
                }
            };
            applyResource(0);
            return deferred.promise();
        },

        /**
         * Loads the specified resource into the page.
         * @param resource The resource to be loaded.
         * @returns {Promise} A promise representing the loading of the resource.
         */
        loadResource: function(resource) {
            var resIsArray = $.isArray(resource);
            var head = $('head'),
                kind = resIsArray ? resource[0] : resource.kind,
                data = resIsArray ? resource[1] : resource.data,
                mimetype = resIsArray ? resource[2] : resource.mimetype,
                placement = resIsArray ? resource[3] : resource.placement;
            if (mimetype === 'text/css') {
                if (kind === 'text') {
                    head.append("<style type='text/css'>" + data + '</style>');
                } else if (kind === 'url') {
                    head.append("<link rel='stylesheet' href='" + data + "' type='text/css'>");
                }
            } else if (mimetype === 'application/javascript') {
                if (kind === 'text') {
                    head.append('<script>' + data + '</script>');
                } else if (kind === 'url') {
                    return this.loadJavaScript(data);
                }
            } else if (mimetype === 'text/html') {
                if (placement === 'head') {
                    head.append(data);
                }
            }
            // Return an already resolved promise for synchronous updates
            return $.Deferred().resolve().promise();
        },

        /**
         * Dynamically loads the specified JavaScript file.
         * @param url The URL to a JavaScript file.
         * @returns {Promise} A promise indicating when the URL has been loaded.
         */
        loadJavaScript: function(url) {
            var deferred = $.Deferred();
            require([url],
                function() {
                    deferred.resolve();
                },
                function() {
                    deferred.reject();
                });
            return deferred.promise();
        }
    });
    this.XBlockFragment = XBlockFragment;
}).call(this, $, _, Backbone, require || RequireJS.require);
