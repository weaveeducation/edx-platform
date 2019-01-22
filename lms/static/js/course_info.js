$(document).ready(function() {
    $('ul.tabs li').click(function() {
        $('ul.tabs li').removeClass('enabled');
        $(this).addClass('enabled');

        var data_class = '.' + $(this).attr('data-class');

        $('.tab').slideUp();
        $(data_class + ':hidden').slideDown();
    });

    function checkEnrollButton() {
        const tableHeight = $('.table').height();
        if (tableHeight > 410) {
            $('.main-cta').addClass('about-wide-enroll-button');
        }
        else {
            $('.main-cta').removeClass('about-wide-enroll-button');
        }
    }

    window.addEventListener('resize', checkEnrollButton);

    checkEnrollButton();
});
