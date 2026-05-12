you are python expert. 

We are working on creating app that will be base for other apps. 
App is multi platform created in python3.14 abd pyside6.

We are proffesionals. Code should be clean, well organized. Architecture should be well planned, so app is extendable and maintanable. 

Phase 1 - UI base

application should not use system ribbon - it will be custom one as well as resizing window. 

App should consists of multiple sub-apps (panels). business logic of app should be separated from UI. For each sub-app i expect at least 2 files - core.py and ui.py. 

Application window should consist of:
[Header]
[list of apps][Body]
[Footer]


In header
[menu icon] [universal widget] .<empty space>. [theme icon][settings icon][minimize][exit]

menu icon opens (extends) left side panel with icons (names) of all registered sub-apps. 

universal widget can be different for each sub-app - it can be extra button, text, counter, mix of all, etc. 

Settings icon opens sub-app with settings. 


List of apps is side panel minimized by default. When minimized only app icons are visible. Extended shows app name as well. 
list of apps should have easter egg - hidden apps. 
user minimize/maximize side panel 5 times very quickly, hidden apps appears. 


Body - sub-app panel - different for each sub app. On start empty until we click one of sub-apps. 

footer
[panel status]  .<empty space>. [resize corner]

panel status is something that should be implemented for each sub-app - text only - show what is happening with panel. 
like "fetching data ..." "Thinking...", etc. 

Window size/position should be saved in application settings. 

Sub-apps registry - sub-app should be implementation of abstract class that can be registered in main app. It should be easy to create new app. 
After creation / registration of sub-app it should appear on side panel,
After cicking on app, top widget should be connnected as wel as panel status, body in center panel created. If top widget or status panel is not needed, empty implementations should be provided - previous widget must dissapear. App can have specific settings. after registration settings are registered in settings store and presented in settings app. 


Settings sub-app is separate sub-app opened from icon on top bar.
each sub-app can register own settings. Panel should be divided like:

[app title]
[app  settings list]

[Sub-app-1-title]
[sub app 1 settings list]

[Sub-app-2-title]
[sub app 2 settings list]

So settings app agregates all settings from all sub-apps an main app itself. 


Application should support notifications - toasts presented as list of boxes drawn from right upper corner, down.
It should be implemented as separate mechanism, so each sub-app can trigger event. 
There should be 3 classes of toasts - info, warning, error with different colors. They should 

Phase 2 - Demo apps

Create sub-apps:

Counter:
    body - counter - +- buttons,
    top widget - counter status - count
    status panel - increment step
    settings - increment step 1, 5, 10

Dummy:
    hello world
    no settings or extra widgets

Secret app:
    like dummy but hidden :)


let's plan this and create workplan.md file 