"use strict"
function Utils(){}

Utils.request = function (url, options) {
    var spinner = undefined;
    var widget = undefined;
    if (options.selector) {
        // Spinning wheel
        spinner = Utils.createSpinner();
        spinner.spin();
        widget = $(options.selector)
        widget.append(spinner.el);
    }

    $.ajax({
        url: url,
        data: options.data,
        type: options.method || 'get',
        contentType: options.contentType,
        success: function(data) {
            if (options.success) options.success(data, widget);
            if(spinner) spinner.stop();
        },
        error:  function( jqXhr, textStatus, errorThrown) {
            if(spinner) spinner.stop();
            console.log( errorThrown );
            if (options.error) options.error(textStatus, errorThrown);
        }
    })
}

Utils.createSpinner = function() {
    // Spinning wheel
    var spinner = new Spinner({
        lines: 13, // The number of lines to draw
        length: 25, // The length of each line
        width: 6, // The line thickness
        radius: 25, // The radius of the inner circle
        corners: 1, // Corner roundness (0..1)
        color: '#555', // #rgb or #rrggbb or array of colors
        opacity: 0.25, // Opacity of the lines
        rotate: 0, // The rotation offset
        speed: 1, // Rounds per second
        trail: 60, // Afterglow percentage
        shadow: true, // Whether to render a shadow*/
    });
    return spinner;
}

Utils.test = function(value) {
	return value*2;
}

Utils.machineIcon = function(model, size) {
    switch(model) {
            case 'model1':
                //return "/static/img/machines/icons8-bot-{0}.png".format(size);
                return "/static/img/MapMarkers/blue_{0}.png".format(size);
            case 'model2':
                //return "/static/img/machines/icons8-robot-3-{0}.png".format(size);
                return "/static/img/MapMarkers/yellow_{0}.png".format(size);
            case 'model3':
                //return "/static/img/machines/icons8-robot-2-{0}.png".format(size);
                return "/static/img/MapMarkers/green_{0}.png".format(size);
            case 'model4':
                //return "/static/img/machines/icons8-robot-{0}.png".format(size);
                return "/static/img/MapMarkers/red_{0}.png".format(size);
    }
}

Utils.machineGaugeIcon = function(value) {
	switch(value) {
            case (value < 15):
                return "/static/img/gauges/gaugevlow.gif";
            case (value < 30):
                return "/static/img/gauges/gaugelow.gif";
            case (value < 45):
                return "/static/img/gauges/gaugemlow.gif";
            case (value < 60):
                return "/static/img/gauges/gaugemedium.gif";
            case (value < 75):
                return "/static/img/gauges/gaugemhigh.gif";
            case (value < 90):
                return "/static/img/gauges/gaugehigh.gif";
        	case (value < 99):
                return "/static/img/gauges/gaugevhigh.gif";
    }	 
}

// taken from https://stackoverflow.com/questions/610406/javascript-equivalent-to-printf-string-format
// First, checks if it isn't implemented yet.
if (!String.prototype.format) {
  String.prototype.format = function() {
    var args = arguments;
    return this.replace(/{(\d+)}/g, function(match, number) {
      return typeof args[number] != 'undefined'
        ? args[number]
        : match
      ;
    });
  };
}