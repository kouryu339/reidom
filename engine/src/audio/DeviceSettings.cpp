#include "DeviceSettings.h"

#include <algorithm>
#include <initializer_list>
#include <utility>

namespace reidom::audio {
namespace {

juce::var object(std::initializer_list<std::pair<juce::Identifier, juce::var>> values) {
    auto* result = new juce::DynamicObject();
    for (const auto& [name, value] : values)
        result->setProperty(name, value);
    return juce::var(result);
}

juce::var array(const std::vector<juce::var>& values) {
    juce::Array<juce::var> result;
    for (const auto& value : values)
        result.add(value);
    return juce::var(result);
}

}  // namespace

juce::var describeDeviceSettings(juce::AudioDeviceManager& manager) {
    std::vector<juce::var> outputDevices;
    for (auto* type : manager.getAvailableDeviceTypes()) {
        type->scanForDevices();
        for (const auto& name : type->getDeviceNames(false))
            outputDevices.push_back(object({{"type", type->getTypeName()}, {"name", name}}));
    }

    std::vector<juce::var> midiInputs;
    for (const auto& device : juce::MidiInput::getAvailableDevices()) {
        midiInputs.push_back(object({
            {"id", device.identifier},
            {"name", device.name},
            {"enabled", manager.isMidiInputDeviceEnabled(device.identifier)},
        }));
    }

    std::vector<juce::var> sampleRates;
    std::vector<juce::var> bufferSizes;
    auto currentOutput = juce::String{};
    auto currentType = manager.getCurrentAudioDeviceType();
    auto currentSampleRate = 0.0;
    auto currentBufferSize = 0;
    if (auto* device = manager.getCurrentAudioDevice()) {
        currentOutput = device->getName();
        currentSampleRate = device->getCurrentSampleRate();
        currentBufferSize = device->getCurrentBufferSizeSamples();
        for (const auto rate : device->getAvailableSampleRates())
            sampleRates.push_back(rate);
        for (const auto size : device->getAvailableBufferSizes())
            bufferSizes.push_back(size);
    }

    return object({
        {"schema", "reidom-device-settings/v1"},
        {"audio", object({
            {"device_type", currentType},
            {"output_device", currentOutput},
            {"sample_rate", currentSampleRate},
            {"buffer_size", currentBufferSize},
            {"output_devices", array(outputDevices)},
            {"sample_rates", array(sampleRates)},
            {"buffer_sizes", array(bufferSizes)},
        })},
        {"midi_inputs", array(midiInputs)},
    });
}

std::optional<juce::String> configureDeviceSettings(
    juce::AudioDeviceManager& manager,
    const juce::String& outputDevice,
    double sampleRate,
    int bufferSize,
    const std::vector<juce::String>& enabledMidiInputIds) {
    auto setup = manager.getAudioDeviceSetup();
    if (outputDevice.isNotEmpty())
        setup.outputDeviceName = outputDevice;
    if (sampleRate > 0.0)
        setup.sampleRate = sampleRate;
    if (bufferSize > 0)
        setup.bufferSize = bufferSize;
    setup.useDefaultOutputChannels = true;

    const auto error = manager.setAudioDeviceSetup(setup, true);
    if (error.isNotEmpty())
        return error;

    for (const auto& device : juce::MidiInput::getAvailableDevices()) {
        const auto enabled = std::ranges::find(enabledMidiInputIds, device.identifier) !=
            enabledMidiInputIds.end();
        manager.setMidiInputDeviceEnabled(device.identifier, enabled);
    }
    return std::nullopt;
}

}  // namespace reidom::audio
