var _auto_night_mode_init = false;
document$.subscribe(() => {
    if(_auto_night_mode_init) return;
    _auto_night_mode_init = true;

    if(!window.SunCalc) return;

    var checked_el;
    [].forEach.call(document.querySelectorAll("form[data-md-component=palette] input"), (input) => {
        if(input.checked) checked_el = input;
    });

    var auto_theme_checkbox = document.getElementById("__palette_0");
    if(!checked_el)
        auto_theme_checkbox.checked = true;

    auto_theme_checkbox.addEventListener("change", () => {
        if(auto_theme_checkbox.checked) auto_night_mode();
    });

    var setTheme = (theme) => document.body.setAttribute("data-md-color-scheme", theme);

    var response;

    var auto_night_mode = (date_for_calc) => {
        // if the automatic mode is unchecked, don't do anything
        if(!auto_theme_checkbox.checked) return;

        var date = new Date();  // current date
        var date_for_calc = date_for_calc || new Date();  // date to check
        var times = SunCalc.getTimes(date_for_calc, response.lat, response.lon);  // sunrise and sunset times

        var target_date;

        if(date < times.sunrise) {  // before the sunrise = night mode
            setTheme("slate");
            target_date = times.sunrise;
        } else if (date < times.sunset) {  // before the sunset = day mode
            setTheme("default");
            target_date = times.sunset;
        } else {  // after the sunset = check the next day (will be night mode)
            date_for_calc.setDate(date_for_calc.getDate() + 1);
            auto_night_mode(date_for_calc, response);
            return;
        }

        setTimeout(auto_night_mode, target_date - date);  // re-check the mode at sunrise/sunset
    };

    // get location from IP address
    fetch("http://ip-api.com/json?fields=lat,lon")
    .then(res => res.json())
    .then(_response => {
        response = _response;
        auto_night_mode();
    })
    .catch((error) => {
        console.log("Can't run auto night mode");
        console.error(error);
    });
});
