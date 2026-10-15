#pragma once

#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_core/juce_core.h>

#include <optional>
#include <vector>

namespace reidom::audio {

juce::var describeDeviceSettings(juce::AudioDeviceManager& manager);

std::optional<juce::String> configureDeviceSettings(
    juce::AudioDeviceManager& manager,
    const juce::String& outputDevice,
    double sampleRate,
    int bufferSize,
    const std::vector<juce::String>& enabledMidiInputIds);

}  // namespace reidom::audio
