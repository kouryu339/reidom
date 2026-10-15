#include "JsonUtils.h"

#include <algorithm>
#include <cmath>

namespace reidom::engine {

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

juce::String stringProperty(const juce::var& value, const char* name,
                            const juce::String& fallback) {
    if (const auto* dynamic = value.getDynamicObject()) {
        const auto property = dynamic->getProperty(name);
        if (!property.isVoid())
            return property.toString();
    }
    return fallback;
}

double doubleProperty(const juce::var& value, const char* name, double fallback) {
    if (const auto* dynamic = value.getDynamicObject()) {
        const auto property = dynamic->getProperty(name);
        if (property.isDouble() || property.isInt() || property.isInt64() || property.isBool())
            return static_cast<double>(property);
    }
    return fallback;
}

int intProperty(const juce::var& value, const char* name, int fallback) {
    return static_cast<int>(std::lround(doubleProperty(value, name, fallback)));
}

bool boolProperty(const juce::var& value, const char* name, bool fallback) {
    if (const auto* dynamic = value.getDynamicObject()) {
        const auto property = dynamic->getProperty(name);
        if (property.isBool() || property.isInt() || property.isInt64())
            return static_cast<bool>(property);
    }
    return fallback;
}

juce::var property(const juce::var& value, const char* name) {
    if (const auto* dynamic = value.getDynamicObject())
        return dynamic->getProperty(name);
    return {};
}

std::vector<juce::String> stringArrayProperty(const juce::var& value, const char* name) {
    std::vector<juce::String> result;
    if (const auto* items = property(value, name).getArray()) {
        result.reserve(static_cast<size_t>(items->size()));
        for (const auto& item : *items)
            result.push_back(item.toString());
    }
    return result;
}

juce::var effectSettingsVar(const reidom::audio::TrackEffectSettings& settings) {
    return object({
        {"eq", object({
            {"enabled", settings.eqEnabled},
            {"low_gain_db", settings.lowGainDb},
            {"mid_gain_db", settings.midGainDb},
            {"high_gain_db", settings.highGainDb},
        })},
        {"compressor", object({
            {"enabled", settings.compressorEnabled},
            {"threshold_db", settings.compressorThresholdDb},
            {"ratio", settings.compressorRatio},
        })},
        {"delay", object({
            {"enabled", settings.delayEnabled},
            {"time_ms", settings.delayTimeMs},
            {"feedback", settings.delayFeedback},
            {"mix", settings.delayMix},
        })},
        {"reverb", object({
            {"enabled", settings.reverbEnabled},
            {"room_size", settings.reverbRoomSize},
            {"mix", settings.reverbMix},
        })},
    });
}

void readEffectSettings(
    reidom::audio::TrackEffectSettings& settings, const juce::var& value) {
    const auto eq = property(value, "eq");
    settings.eqEnabled = boolProperty(eq, "enabled", settings.eqEnabled);
    settings.lowGainDb = static_cast<float>(std::clamp(
        doubleProperty(eq, "low_gain_db", settings.lowGainDb), -12.0, 12.0));
    settings.midGainDb = static_cast<float>(std::clamp(
        doubleProperty(eq, "mid_gain_db", settings.midGainDb), -12.0, 12.0));
    settings.highGainDb = static_cast<float>(std::clamp(
        doubleProperty(eq, "high_gain_db", settings.highGainDb), -12.0, 12.0));
    const auto compressor = property(value, "compressor");
    settings.compressorEnabled = boolProperty(
        compressor, "enabled", settings.compressorEnabled);
    settings.compressorThresholdDb = static_cast<float>(std::clamp(
        doubleProperty(compressor, "threshold_db", settings.compressorThresholdDb),
        -48.0, 0.0));
    settings.compressorRatio = static_cast<float>(std::clamp(
        doubleProperty(compressor, "ratio", settings.compressorRatio), 1.0, 12.0));
    const auto delay = property(value, "delay");
    settings.delayEnabled = boolProperty(delay, "enabled", settings.delayEnabled);
    settings.delayTimeMs = static_cast<float>(std::clamp(
        doubleProperty(delay, "time_ms", settings.delayTimeMs), 20.0, 1500.0));
    settings.delayFeedback = static_cast<float>(std::clamp(
        doubleProperty(delay, "feedback", settings.delayFeedback), 0.0, 0.82));
    settings.delayMix = static_cast<float>(std::clamp(
        doubleProperty(delay, "mix", settings.delayMix), 0.0, 0.65));
    const auto reverb = property(value, "reverb");
    settings.reverbEnabled = boolProperty(reverb, "enabled", settings.reverbEnabled);
    settings.reverbRoomSize = static_cast<float>(std::clamp(
        doubleProperty(reverb, "room_size", settings.reverbRoomSize), 0.0, 1.0));
    settings.reverbMix = static_cast<float>(std::clamp(
        doubleProperty(reverb, "mix", settings.reverbMix), 0.0, 0.65));
}

juce::String newId(const juce::String& prefix) {
    return prefix + "-" + juce::Uuid().toString().substring(0, 12);
}

}  // namespace reidom::engine
