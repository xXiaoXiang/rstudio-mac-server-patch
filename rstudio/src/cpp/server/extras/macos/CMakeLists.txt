cmake_minimum_required(VERSION 3.25)

project(RStudioServerControl LANGUAGES OBJC)
find_library(RSERVER_COCOA_FRAMEWORK Cocoa REQUIRED)
find_library(RSERVER_SERVICE_MANAGEMENT_FRAMEWORK ServiceManagement REQUIRED)

add_executable(rstudio-server-app MACOSX_BUNDLE ServerApp.m ServerAdmin.m)
set_target_properties(rstudio-server-app PROPERTIES
   OUTPUT_NAME RStudioServer
   MACOSX_BUNDLE_INFO_PLIST "${CMAKE_CURRENT_SOURCE_DIR}/Info.plist.in")
if(NOT DEFINED CPACK_PACKAGE_VERSION_MAJOR)
   set(CPACK_PACKAGE_VERSION_MAJOR 0)
   set(CPACK_PACKAGE_VERSION_MINOR 0)
   set(CPACK_PACKAGE_VERSION_PATCH 0)
endif()
target_compile_options(rstudio-server-app PRIVATE -fobjc-arc)
target_link_libraries(rstudio-server-app
   "${RSERVER_COCOA_FRAMEWORK}" "${RSERVER_SERVICE_MANAGEMENT_FRAMEWORK}")
install(TARGETS rstudio-server-app BUNDLE DESTINATION .)
