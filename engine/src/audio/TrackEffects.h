#pragma once

#include <juce_dsp/juce_dsp.h>

#include <vector>

namespace reidom::audio {

struct TrackEffectSettings {
    bool eqEnabled = false;
    float lowGainDb = 0.0f;
    float midGainDb = 0.0f;
    float highGainDb = 0.0f;

    bool compressorEnabled = false;
    float compressorThresholdDb = -18.0f;
    float compressorRatio = 3.0f;

    bool delayEnabled = false;
    float delayTimeMs = 240.0f;
    float delayFeedback = 0.24f;
    float delayMix = 0.12f;

    bool reverbEnabled = false;
    float reverbRoomSize = 0.38f;
    float reverbMix = 0.14f;

    bool operator==(const TrackEffectSettings&) const = default;
};

class TrackEffectProcessor {
public:
    void prepare(double sampleRate, double maximumDelaySeconds = 2.0);
    void reset();
    void configure(const TrackEffectSettings& settings);
    void processSample(float& left, float& right) noexcept;

private:
    float applyEq(float sample, float& lowState, float& highState) noexcept;

    TrackEffectSettings settings_;
    bool configured_ = false;
    double sampleRate_ = 44100.0;
    float lowCoefficient_ = 0.0f;
    float highCoefficient_ = 0.0f;
    float lowGain_ = 1.0f;
    float midGain_ = 1.0f;
    float highGain_ = 1.0f;
    float compressorThreshold_ = 0.125f;
    float compressorRatio_ = 3.0f;
    float compressorAttack_ = 0.0f;
    float compressorRelease_ = 0.0f;
    float compressorEnvelope_ = 0.0f;
    float lowStateLeft_ = 0.0f;
    float lowStateRight_ = 0.0f;
    float highStateLeft_ = 0.0f;
    float highStateRight_ = 0.0f;
    std::vector<float> delayLeft_;
    std::vector<float> delayRight_;
    int delayWriteIndex_ = 0;
    int delaySamples_ = 1;
    juce::Reverb reverb_;
};

}  // namespace reidom::audio

