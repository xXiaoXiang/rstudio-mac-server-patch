

# shared cpack variables
set(CPACK_PACKAGE_NAME "RStudio")
set(CPACK_PACKAGE_DESCRIPTION "RStudio")
set(CPACK_PACKAGE_VENDOR "Posit Software")
set(CPACK_PACKAGE_CONTACT "RStudio <info@posit.co>")
set(CPACK_PACKAGE_INSTALL_DIRECTORY "RStudio")

if(WIN32)

   add_subdirectory(win32)

elseif(APPLE)

   # The macOS packaging pipeline merges and signs an Electron app bundle.
   # Native Server builds use cmake --install and a launchd service instead.
   if(RSTUDIO_ELECTRON)
      add_subdirectory(osx)
   endif()

elseif(LINUX)

   add_subdirectory(linux)

endif()
