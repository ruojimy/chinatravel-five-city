@echo off
setlocal
set "EDGE=C://Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
set "UDD=%~dp0..\.edge-debug-profile"
start "" "%EDGE%" --remote-debugging-port=9222 --user-data-dir="%UDD%" --no-first-run --no-default-browser-check "https://passport.meituan.com/account/unitivelogin" "https://i.meituan.com/awp/h5/hotel/search/search.html" "https://passport.ctrip.com/user/login" "https://www.booking.com/searchresults.zh-cn.html?ss=%E8%A5%BF%E5%AE%89&selected_currency=CNY"
endlocal
