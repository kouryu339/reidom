#pragma once

#include <juce_audio_basics/juce_audio_basics.h>
#include <juce_audio_devices/juce_audio_devices.h>
#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_core/juce_core.h>

#include <array>
#include <atomic>
#include <memory>
#include <mutex>
#include <optional>
#include <vector>

#include "EngineTypes.h"

namespace reidom::engine {

class ReidomEngine final : private juce::AudioIODeviceCallback,
                           private juce::MidiInputCallback {
public:
    ReidomEngine();

    ~ReidomEngine() override;

    juce::var handle(const juce::var& request);

    bool shouldStop() const;

    bool selfTest();

private:
    juce::var health() const;

    juce::var configureDevices(const juce::var& request);

    juce::var applyCommand(const juce::var& command);

    std::optional<juce::String> mutate(const juce::String& type, const juce::var& payload);

    std::optional<juce::String> addArrangementTrack(const juce::var& payload);

    std::optional<juce::String> mutateRoute(const juce::var& payload);

    std::optional<juce::String> mutateEffects(const juce::var& payload);

    std::optional<juce::String> mutateTracks(const juce::String& type, const juce::var& payload);

    std::optional<juce::String> mutateNotes(const juce::String& type, const juce::var& payload);

    std::optional<juce::String> mutateClips(const juce::String& type, const juce::var& payload);

    juce::var undo();

    juce::var redo();

    juce::var importMidi(const juce::var& request);

    juce::var exportMidi() const;

    juce::var exportProject() const;

    juce::var importProject(const juce::var& request);

    juce::var renderWav() const;

    juce::var snapshotBundle() const;

    juce::var projectVar(const juce::var& selection) const;

    juce::var selectionVar() const;

    juce::var clipVar(const Clip& clip) const;

    static juce::var noteVar(const Note& note, const juce::String& trackId,
                             const juce::String& clipId);

    juce::var transportVar() const;

    static BuiltinVoice voiceForInstrument(const juce::String& instrument, const juce::String& role);

    void rebuildAudioSnapshot();

    void resetTransport();

    void drainRecordedNotes();

    void finishActiveMidiNotes(double endBeat);

    static double beatsFromPosition(const juce::String& position);

    static juce::String positionFromBeats(double value);

    static double oscillator(BuiltinVoice voice, int pitch, double elapsedSeconds, double durationSeconds);

    void audioDeviceIOCallbackWithContext(const float* const*, int,
                                          float* const* outputs, int numOutputs,
                                          int numSamples,
                                          const juce::AudioIODeviceCallbackContext&) override;

    void handleIncomingMidiMessage(juce::MidiInput*, const juce::MidiMessage& message) override;

    void audioDeviceAboutToStart(juce::AudioIODevice* device) override;

    void audioDeviceStopped() override;

    juce::var historyVar() const;

    juce::var commandLog() const;


    double projectEnd() const;

    Track* findTrack(const juce::String& id);

    Clip* findClip(const juce::String& id);

    static void assignBool(const juce::var& source, const char* name, bool& destination);

    void pushUndo();

    static juce::String colorForTrack(int index);

    static ProjectState demoProject();

    static juce::var ok(juce::var result);

    static juce::var error(const juce::String& code, const juce::String& message);

private:
    juce::var editState() const;
    juce::var editMode(const juce::var& request);
    juce::var document() const;
    juce::var editDocument(const juce::var& request);
    void publishDocument() const;
    bool manualEditing_ = false;
    int64_t editEpoch_ = 0;
    juce::String publicationError_;
    mutable std::mutex mutex_;
    ProjectState project_;
    std::vector<ProjectState> undo_;
    std::vector<ProjectState> redo_;
    std::vector<CommandRecord> log_;
    juce::AudioDeviceManager audioDeviceManager_;
    juce::String audioError_;
    std::vector<juce::String> midiInputIds_;
    std::vector<juce::String> midiInputNames_;
    std::mutex midiMutex_;
    std::vector<ActiveMidiNote> activeMidiNotes_;
    std::vector<PendingMidiNote> pendingMidiNotes_;
    std::atomic<std::shared_ptr<const std::vector<LiveMidiNote>>> liveMidiNotes_{
        std::make_shared<const std::vector<LiveMidiNote>>()};
    std::atomic<std::shared_ptr<const AudioSnapshot>> audioSnapshot_;
    std::optional<ProjectState> recordingStartState_;
    std::array<reidom::audio::TrackEffectProcessor, kMaxRealtimeTracks> trackEffectProcessors_;
    bool recordedInTake_ = false;
    bool justFinalizedRecording_ = false;
    std::atomic<double> playheadBeats_{0.0};
    std::atomic<double> sampleRate_{44100.0};
    std::atomic_bool playing_{false};
    std::atomic_bool effectsResetRequested_{false};
    std::atomic_bool recording_{false};
    std::atomic_bool shouldStop_{false};
};

}  // namespace reidom::engine
