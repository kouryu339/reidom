#include "../core/ReidomEngine.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <utility>

#include "../audio/DeviceSettings.h"
#include "../protocol/JsonUtils.h"

namespace reidom::engine {

BuiltinVoice ReidomEngine::voiceForInstrument(const juce::String& instrument, const juce::String& role) {
    const auto value = (instrument + " " + role).toLowerCase();
    if (value.contains("drum") || value.contains("percussion")) return BuiltinVoice::drums;
    if (value.contains("bass")) return BuiltinVoice::bass;
    if (value.contains("guitar")) return BuiltinVoice::guitar;
    if (value.contains("pad") || value.contains("string")) return BuiltinVoice::pad;
    if (value.contains("lead") || value.contains("synth")) return BuiltinVoice::lead;
    return BuiltinVoice::piano;
}

void ReidomEngine::rebuildAudioSnapshot() {
    auto next = std::make_shared<AudioSnapshot>();
    next->tempo = project_.transport.tempo;
    next->loop = project_.transport.loop;
    next->metronome = project_.transport.metronome;
    next->endBeat = std::max(1.0, projectEnd());
    next->loopStartBeat = std::clamp(project_.transport.loopStartBeat, 0.0, next->endBeat);
    next->loopEndBeat = project_.transport.loopEndBeat > next->loopStartBeat
        ? std::min(project_.transport.loopEndBeat, next->endBeat)
        : next->endBeat;
    const auto anySolo = std::ranges::any_of(project_.tracks, &Track::solo);
    for (const auto& track : project_.tracks) {
        RenderTrack renderTrack;
        renderTrack.id = track.id;
        renderTrack.audible = !track.mute && (!anySolo || track.solo);
        renderTrack.effects = track.effects;
        if (track.arm) {
            next->recordTargets.push_back({
                track.id,
                voiceForInstrument(track.instrument, track.role),
                track.volume,
                track.pan,
                track.monitor,
            });
        }
        const auto voice = voiceForInstrument(track.instrument, track.role);
        if (renderTrack.audible) {
            for (const auto& clip : project_.clips) {
                if (clip.trackId != track.id)
                    continue;
                const auto clipEnd = clip.start + clip.duration;
                for (const auto& note : clip.notes) {
                    if (note.start >= clipEnd)
                        continue;
                    renderTrack.notes.push_back({
                        note.start,
                        std::min(note.start + note.duration, clipEnd),
                        note.pitch,
                        track.volume * (static_cast<double>(note.velocity) / 127.0),
                        track.pan,
                        voice,
                    });
                }
            }
        }
        next->tracks.push_back(std::move(renderTrack));
    }
    audioSnapshot_.store(std::move(next));
}

void ReidomEngine::resetTransport() {
    playing_.store(false);
    recording_.store(false);
    playheadBeats_.store(0.0);
    project_.transport.playing = false;
    project_.transport.recording = false;
    project_.transport.position = "001.1.1";
    recordingStartState_.reset();
    recordedInTake_ = false;
    effectsResetRequested_.store(true);
    std::scoped_lock midiLock(midiMutex_);
    activeMidiNotes_.clear();
    pendingMidiNotes_.clear();
    liveMidiNotes_.store(std::make_shared<const std::vector<LiveMidiNote>>());
}

void ReidomEngine::drainRecordedNotes() {
    std::vector<PendingMidiNote> pending;
    {
        std::scoped_lock midiLock(midiMutex_);
        pending.swap(pendingMidiNotes_);
    }
    if (pending.empty())
        return;
    for (const auto& captured : pending) {
        if (findTrack(captured.trackId) == nullptr)
            continue;
        auto found = std::find_if(project_.clips.begin(), project_.clips.end(), [&](const Clip& clip) {
            return clip.trackId == captured.trackId && captured.startBeat >= clip.start &&
                captured.startBeat < clip.start + clip.duration;
        });
        if (found == project_.clips.end()) {
            Clip clip;
            clip.id = newId("clip");
            clip.trackId = captured.trackId;
            clip.name = "Recorded MIDI";
            clip.start = std::floor(captured.startBeat / 4.0) * 4.0;
            clip.duration = std::max(4.0, captured.startBeat + captured.durationBeats - clip.start);
            project_.clips.push_back(std::move(clip));
            found = std::prev(project_.clips.end());
        }
        found->duration = std::max(found->duration,
            captured.startBeat + captured.durationBeats - found->start);
        found->notes.push_back({
            newId("note"), captured.pitch, captured.startBeat,
            std::max(0.03125, captured.durationBeats), captured.velocity,
        });
        recordedInTake_ = true;
    }
    rebuildAudioSnapshot();
}

void ReidomEngine::finishActiveMidiNotes(double endBeat) {
    std::scoped_lock midiLock(midiMutex_);
    const auto snapshot = audioSnapshot_.load();
    const auto loopLength = snapshot ? snapshot->loopEndBeat - snapshot->loopStartBeat : 0.0;
    for (const auto& active : activeMidiNotes_) {
        auto duration = endBeat - active.startBeat;
        if (duration <= 0.0 && snapshot && snapshot->loop)
            duration += loopLength;
        pendingMidiNotes_.push_back({
            active.trackId, active.pitch, active.velocity, active.startBeat,
            std::max(0.03125, duration),
        });
    }
    activeMidiNotes_.clear();
    liveMidiNotes_.store(std::make_shared<const std::vector<LiveMidiNote>>());
}

double ReidomEngine::beatsFromPosition(const juce::String& position) {
    const auto parts = juce::StringArray::fromTokens(position, ".", {});
    if (parts.size() < 2)
        return 0.0;
    const auto bar = std::max(1, parts[0].getIntValue());
    const auto beat = std::max(1, parts[1].getIntValue());
    const auto subdivision = parts.size() > 2 ? std::max(1, parts[2].getIntValue()) : 1;
    return (bar - 1) * 4.0 + (beat - 1) + (subdivision - 1) * 0.25;
}

juce::String ReidomEngine::positionFromBeats(double value) {
    value = std::max(0.0, value);
    const auto bar = static_cast<int>(std::floor(value / 4.0)) + 1;
    const auto within = value - (bar - 1) * 4.0;
    const auto beat = static_cast<int>(std::floor(within)) + 1;
    const auto subdivision = std::clamp(static_cast<int>(std::floor((within - std::floor(within)) * 4.0 + 0.001)) + 1, 1, 4);
    return juce::String(bar).paddedLeft('0', 3) + "." + juce::String(beat) + "." + juce::String(subdivision);
}

double ReidomEngine::oscillator(BuiltinVoice voice, int pitch, double elapsedSeconds, double durationSeconds) {
    constexpr auto twoPi = juce::MathConstants<double>::twoPi;
    const auto frequency = 440.0 * std::pow(2.0, (pitch - 69) / 12.0);
    const auto phase = twoPi * frequency * elapsedSeconds;
    const auto attack = std::min(1.0, elapsedSeconds / (voice == BuiltinVoice::pad ? 0.18 : 0.008));
    const auto releaseTime = voice == BuiltinVoice::pad ? 0.3 : 0.08;
    const auto release = std::min(1.0, std::max(0.0, durationSeconds - elapsedSeconds) / releaseTime);
    const auto envelope = attack * release;
    if (voice == BuiltinVoice::drums) {
        const auto decay = std::exp(-elapsedSeconds * (pitch <= 40 ? 14.0 : 28.0));
        const auto noise = std::sin(phase * 17.31 + std::sin(phase * 0.37) * 9.0);
        const auto body = std::sin(twoPi * (pitch <= 40 ? 58.0 : 180.0) * elapsedSeconds);
        return decay * (pitch <= 40 ? body : noise * 0.55);
    }
    if (voice == BuiltinVoice::bass)
        return envelope * (std::sin(phase) >= 0.0 ? 0.72 : -0.72);
    if (voice == BuiltinVoice::guitar) {
        const auto saw = 2.0 * (frequency * elapsedSeconds - std::floor(frequency * elapsedSeconds + 0.5));
        return envelope * std::exp(-elapsedSeconds * 1.5) * (0.58 * saw + 0.32 * std::sin(phase));
    }
    if (voice == BuiltinVoice::pad)
        return envelope * (0.52 * std::sin(phase) + 0.24 * std::sin(phase * 0.501) + 0.18 * std::sin(phase * 1.997));
    if (voice == BuiltinVoice::lead)
        return envelope * (0.72 * std::sin(phase) + 0.2 * std::sin(phase * 2.0));
    return envelope * std::exp(-elapsedSeconds * 2.2) *
        (0.72 * std::sin(phase) + 0.2 * std::sin(phase * 2.01) + 0.08 * std::sin(phase * 3.99));
}

void ReidomEngine::audioDeviceIOCallbackWithContext(const float* const*, int,
                                      float* const* outputs, int numOutputs,
                                      int numSamples,
                                      const juce::AudioIODeviceCallbackContext&) {
    for (int channel = 0; channel < numOutputs; ++channel)
        juce::FloatVectorOperations::clear(outputs[channel], numSamples);
    if (effectsResetRequested_.exchange(false)) {
        for (auto& processor : trackEffectProcessors_)
            processor.reset();
    }
    if (numOutputs == 0)
        return;
    const auto snapshot = audioSnapshot_.load();
    if (!snapshot)
        return;
    const auto liveNotes = liveMidiNotes_.load();
    if (!playing_.load() && (!liveNotes || liveNotes->empty()))
        return;
    const auto configuredTrackCount = std::min(
        snapshot->tracks.size(), trackEffectProcessors_.size());
    for (std::size_t index = 0; index < configuredTrackCount; ++index)
        trackEffectProcessors_[index].configure(snapshot->tracks[index].effects);

    auto beat = playheadBeats_.load();
    const auto rate = sampleRate_.load();
    const auto beatsPerSample = snapshot->tempo / (60.0 * rate);
    const auto secondsPerBeat = 60.0 / snapshot->tempo;
    const auto bufferStartSeconds = juce::Time::getMillisecondCounterHiRes() * 0.001;
    for (int sample = 0; sample < numSamples; ++sample) {
        const auto playbackEnd = snapshot->loop ? snapshot->loopEndBeat : snapshot->endBeat;
        if (playing_.load() && beat >= playbackEnd) {
            if (snapshot->loop)
                beat = snapshot->loopStartBeat;
            else {
                playing_.store(false);
                recording_.store(false);
            }
        }

        double left = 0.0;
        double right = 0.0;
        const auto nowSeconds = bufferStartSeconds + static_cast<double>(sample) / rate;
        for (std::size_t trackIndex = 0; trackIndex < snapshot->tracks.size(); ++trackIndex) {
            const auto& track = snapshot->tracks[trackIndex];
            if (!track.audible)
                continue;
            float trackLeft = 0.0f;
            float trackRight = 0.0f;
            if (playing_.load()) {
                for (const auto& note : track.notes) {
                    if (beat < note.startBeat || beat >= note.endBeat)
                        continue;
                    const auto elapsed = (beat - note.startBeat) * secondsPerBeat;
                    const auto duration = (note.endBeat - note.startBeat) * secondsPerBeat;
                    const auto value = oscillator(
                        note.voice, note.pitch, elapsed, duration) * note.gain * 0.16;
                    trackLeft += static_cast<float>(
                        value * std::sqrt((1.0 - note.pan) * 0.5));
                    trackRight += static_cast<float>(
                        value * std::sqrt((1.0 + note.pan) * 0.5));
                }
            }
            if (liveNotes) {
                for (const auto& note : *liveNotes) {
                    if (note.trackId != track.id)
                        continue;
                    const auto elapsed = std::max(0.0, nowSeconds - note.startedSeconds);
                    const auto value = oscillator(
                        note.voice, note.pitch, elapsed, elapsed + 1.0) * note.gain * 0.14;
                    trackLeft += static_cast<float>(
                        value * std::sqrt((1.0 - note.pan) * 0.5));
                    trackRight += static_cast<float>(
                        value * std::sqrt((1.0 + note.pan) * 0.5));
                }
            }
            if (trackIndex < trackEffectProcessors_.size())
                trackEffectProcessors_[trackIndex].processSample(trackLeft, trackRight);
            left += trackLeft;
            right += trackRight;
        }

        if (playing_.load() && snapshot->metronome) {
            const auto beatFraction = beat - std::floor(beat);
            const auto clickSeconds = beatFraction * secondsPerBeat;
            if (clickSeconds < 0.035) {
                const auto accent = static_cast<int>(std::floor(beat)) % 4 == 0;
                const auto click = std::sin(
                    juce::MathConstants<double>::twoPi *
                    (accent ? 1320.0 : 990.0) * clickSeconds) *
                    std::exp(-clickSeconds * 80.0) * 0.12;
                left += click;
                right += click;
            }
        }
        outputs[0][sample] = static_cast<float>(std::tanh(left));
        if (numOutputs > 1)
            outputs[1][sample] = static_cast<float>(std::tanh(right));
        if (playing_.load())
            beat += beatsPerSample;
    }
    playheadBeats_.store(beat);
}

void ReidomEngine::handleIncomingMidiMessage(juce::MidiInput*, const juce::MidiMessage& message) {
    if (!message.isNoteOnOrOff())
        return;
    const auto snapshot = audioSnapshot_.load();
    if (!snapshot || snapshot->recordTargets.empty())
        return;
    const auto pitch = message.getNoteNumber();
    const auto channel = message.getChannel();
    const auto nowBeat = playheadBeats_.load();
    std::scoped_lock midiLock(midiMutex_);
    auto live = liveMidiNotes_.load();
    auto updatedLive = live ? *live : std::vector<LiveMidiNote>{};
    if (message.isNoteOn()) {
        for (const auto& target : snapshot->recordTargets) {
            if (target.monitor) {
                updatedLive.push_back({
                    target.trackId, channel, pitch,
                    target.gain * message.getFloatVelocity(), target.pan,
                    juce::Time::getMillisecondCounterHiRes() * 0.001, target.voice,
                });
            }
            if (recording_.load()) {
                activeMidiNotes_.push_back({
                    target.trackId, channel, pitch,
                    std::clamp(static_cast<int>(std::lround(message.getFloatVelocity() * 127.0f)), 1, 127),
                    nowBeat,
                });
            }
        }
    } else {
        std::erase_if(updatedLive, [&](const LiveMidiNote& note) {
            return note.channel == channel && note.pitch == pitch;
        });
        for (auto it = activeMidiNotes_.begin(); it != activeMidiNotes_.end();) {
            if (it->channel != channel || it->pitch != pitch) {
                ++it;
                continue;
            }
            auto duration = nowBeat - it->startBeat;
            if (duration <= 0.0 && snapshot->loop)
                duration += snapshot->endBeat;
            pendingMidiNotes_.push_back({
                it->trackId, it->pitch, it->velocity, it->startBeat,
                std::max(0.03125, duration),
            });
            it = activeMidiNotes_.erase(it);
        }
    }
    liveMidiNotes_.store(std::make_shared<const std::vector<LiveMidiNote>>(std::move(updatedLive)));
}

void ReidomEngine::audioDeviceAboutToStart(juce::AudioIODevice* device) {
    const auto rate = device != nullptr ? device->getCurrentSampleRate() : 44100.0;
    sampleRate_.store(rate);
    for (auto& processor : trackEffectProcessors_)
        processor.prepare(rate);
    effectsResetRequested_.store(false);
}

void ReidomEngine::audioDeviceStopped() {}

}  // namespace reidom::engine
