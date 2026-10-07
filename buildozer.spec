[app]
title = Mycelium Mesh
package.name = myceliummesh
package.domain = org.mycelium

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,html,css,js,json

version = 10.12.0
requirements = python3,kivy,websockets,requests

orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CAMERA, CHANGE_WIFI_MULTICAST_STATE

android.api = 33
android.minapi = 21
android.ndk = 25b
android.build_tools_version = 33.0.2
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
