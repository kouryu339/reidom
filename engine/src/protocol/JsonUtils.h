#pragma once

#include <juce_core/juce_core.h>

#include <initializer_list>
#include <utility>
#include <vector>

#include "../audio/TrackEffects.h"

namespace reidom::engine {

juce::var object(std::initializer_list<std::pair<juce::Identifier, juce::var>> values);
juce::var array(const std::vector<juce::var>& values);
juce::String stringProperty(const juce::var& value, const char* name,
                            const juce::String& fallback = {});
double doubleProperty(const juce::var& value, const char* name, double fallback = 0.0);
int intProperty(const juce::var& value, const char* name, int fallback = 0);
bool boolProperty(const juce::var& value, const char* name, bool fallback = false);
juce::var property(const juce::var& value, const char* name);
std::vector<juce::String> stringArrayProperty(const juce::var& value, const char* name);
juce::var effectSettingsVar(const reidom::audio::TrackEffectSettings& settings);
void readEffectSettings(reidom::audio::TrackEffectSettings& settings, const juce::var& value);
juce::String newId(const juce::String& prefix);

}  // namespace reidom::engine
