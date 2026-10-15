cmake_minimum_required(VERSION 3.22)

project(ReidomEngine VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(JUCE_PATH "${CMAKE_CURRENT_LIST_DIR}/../third_party/JUCE" CACHE PATH "Path to JUCE")
if(NOT EXISTS "${JUCE_PATH}/CMakeLists.txt")
    message(FATAL_ERROR "JUCE not found at ${JUCE_PATH}. Clone JUCE 9.0.0 into third_party/JUCE.")
endif()

add_subdirectory("${JUCE_PATH}" "${CMAKE_BINARY_DIR}/JUCE" EXCLUDE_FROM_ALL)

juce_add_console_app(reidom-engine
    PRODUCT_NAME "Reidom Engine"
    COMPANY_NAME "Reidom"
)

target_sources(reidom-engine PRIVATE
    src/main.cpp
    src/core/EngineTypes.h
    src/core/ReidomEngine.cpp
    src/core/ReidomEngine.h
    src/core/ProjectCommands.cpp
    src/core/DocumentEditing.cpp
    src/core/ProjectIO.cpp
    src/protocol/JsonUtils.cpp
    src/protocol/JsonUtils.h
    src/server/EngineServer.cpp
    src/server/EngineServer.h
    src/audio/DeviceSettings.cpp
    src/audio/DeviceSettings.h
    src/audio/RealtimeAudio.cpp
    src/audio/TrackEffects.cpp
    src/audio/TrackEffects.h
)
target_compile_definitions(reidom-engine PRIVATE
    JUCE_APPLICATION_NAME_STRING="$<TARGET_PROPERTY:reidom-engine,JUCE_PRODUCT_NAME>"
    JUCE_APPLICATION_VERSION_STRING="${PROJECT_VERSION}"
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
)

if(MSVC)
    target_compile_options(reidom-engine PRIVATE /utf-8)
endif()

target_link_libraries(reidom-engine PRIVATE
    juce::juce_audio_basics
    juce::juce_audio_devices
    juce::juce_audio_formats
    juce::juce_audio_processors
    juce::juce_core
    juce::juce_data_structures
    juce::juce_dsp
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags
)

install(TARGETS reidom-engine RUNTIME DESTINATION bin)
