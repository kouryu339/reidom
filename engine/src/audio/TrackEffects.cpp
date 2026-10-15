#include "TrackEffects.h"

#include <algorithm>
#include <cmath>

namespace reidom::audio {

namespace {

float gainFromDecibels(float value) {
    return std::pow(10.0f, value / 20.0f);
}

float smoothingCoefficient(double sampleRate, double seconds) {
    return static_cast<float>(std::exp(-1.0 / (std::max(1.0, sampleRate) * seconds)));
}

}  // namespace

void TrackEffectProcessor::prepare(double sampleRate, double maximumDelaySeconds) {
    sampleRate_ = std::max(8000.0, sampleRate);
    const auto delayCapacity = std::max(
        2, static_cast<int>(std::ceil(sampleRate_ * std::max(0.1, maximumDelaySeconds))));
    delayLeft_.assign(static_cast<size_t>(delayCapacity), 0.0f);
    delayRight_.assign(static_cast<size_t>(delayCapacity), 0.0f);
    reverb_.setSampleRate(sampleRate_);
    lowCoefficient_ = static_cast<float>(1.0 - std::exp(
        -juce::MathConstants<double>::twoPi * 180.0 / sampleRate_));
    highCoefficient_ = static_cast<float>(1.0 - std::exp(
        -juce::MathConstants<double>::twoPi * 3600.0 / sampleRate_));
    compressorAttack_ = smoothingCoefficient(sampleRate_, 0.008);
    compressorRelease_ = smoothingCoefficient(sampleRate_, 0.12);
    reset();
    configured_ = false;
    configure(settings_);
}

void TrackEffectProcessor::reset() {
    lowStateLeft_ = 0.0f;
    lowStateRight_ = 0.0f;
    highStateLeft_ = 0.0f;
    highStateRight_ = 0.0f;
    compressorEnvelope_ = 0.0f;
    delayWriteIndex_ = 0;
    std::fill(delayLeft_.begin(), delayLeft_.end(), 0.0f);
    std::fill(delayRight_.begin(), delayRight_.end(), 0.0f);
    reverb_.reset();
}

void TrackEffectProcessor::configure(const TrackEffectSettings& settings) {
    if (configured_ && settings == settings_)
        return;
    settings_ = settings;
    configured_ = true;
    lowGain_ = gainFromDecibels(std::clamp(settings.lowGainDb, -12.0f, 12.0f));
    midGain_ = gainFromDecibels(std::clamp(settings.midGainDb, -12.0f, 12.0f));
    highGain_ = gainFromDecibels(std::clamp(settings.highGainDb, -12.0f, 12.0f));
    compressorThreshold_ = gainFromDecibels(
        std::clamp(settings.compressorThresholdDb, -48.0f, 0.0f));
    compressorRatio_ = std::clamp(settings.compressorRatio, 1.0f, 12.0f);
    if (!delayLeft_.empty()) {
        delaySamples_ = std::clamp(
            static_cast<int>(std::lround(
                std::clamp(settings.delayTimeMs, 20.0f, 1500.0f) * 0.001 * sampleRate_)),
            1, static_cast<int>(delayLeft_.size()) - 1);
    }
    juce::Reverb::Parameters reverbParameters;
    reverbParameters.roomSize = std::clamp(settings.reverbRoomSize, 0.0f, 1.0f);
    reverbParameters.damping = 0.48f;
    reverbParameters.wetLevel = settings.reverbEnabled
        ? std::clamp(settings.reverbMix, 0.0f, 0.65f)
        : 0.0f;
    reverbParameters.dryLevel = 1.0f;
    reverbParameters.width = 1.0f;
    reverbParameters.freezeMode = 0.0f;
    reverb_.setParameters(reverbParameters);
}

float TrackEffectProcessor::applyEq(
    float sample, float& lowState, float& highState) noexcept {
    lowState += lowCoefficient_ * (sample - lowState);
    highState += highCoefficient_ * (sample - highState);
    const auto low = lowState;
    const auto mid = highState - lowState;
    const auto high = sample - highState;
    return low * lowGain_ + mid * midGain_ + high * highGain_;
}

void TrackEffectProcessor::processSample(float& left, float& right) noexcept {
    if (settings_.eqEnabled) {
        left = applyEq(left, lowStateLeft_, highStateLeft_);
        right = applyEq(right, lowStateRight_, highStateRight_);
    }

    if (settings_.compressorEnabled) {
        const auto peak = std::max(std::abs(left), std::abs(right));
        const auto coefficient = peak > compressorEnvelope_
            ? compressorAttack_
            : compressorRelease_;
        compressorEnvelope_ = coefficient * compressorEnvelope_ + (1.0f - coefficient) * peak;
        if (compressorEnvelope_ > compressorThreshold_) {
            const auto compressed = compressorThreshold_ * std::pow(
                compressorEnvelope_ / compressorThreshold_, 1.0f / compressorRatio_);
            const auto gain = compressed / std::max(compressorEnvelope_, 0.000001f);
            left *= gain;
            right *= gain;
        }
    }

    if (!delayLeft_.empty()) {
        const auto readIndex = (delayWriteIndex_ + static_cast<int>(delayLeft_.size()) - delaySamples_)
            % static_cast<int>(delayLeft_.size());
        const auto delayedLeft = delayLeft_[static_cast<size_t>(readIndex)];
        const auto delayedRight = delayRight_[static_cast<size_t>(readIndex)];
        if (settings_.delayEnabled) {
            const auto feedback = std::clamp(settings_.delayFeedback, 0.0f, 0.82f);
            const auto mix = std::clamp(settings_.delayMix, 0.0f, 0.65f);
            delayLeft_[static_cast<size_t>(delayWriteIndex_)] = left + delayedLeft * feedback;
            delayRight_[static_cast<size_t>(delayWriteIndex_)] = right + delayedRight * feedback;
            left = left * (1.0f - mix) + delayedLeft * mix;
            right = right * (1.0f - mix) + delayedRight * mix;
        } else {
            delayLeft_[static_cast<size_t>(delayWriteIndex_)] = 0.0f;
            delayRight_[static_cast<size_t>(delayWriteIndex_)] = 0.0f;
        }
        delayWriteIndex_ = (delayWriteIndex_ + 1) % static_cast<int>(delayLeft_.size());
    }

    reverb_.processStereo(&left, &right, 1);
}

}  // namespace reidom::audio
