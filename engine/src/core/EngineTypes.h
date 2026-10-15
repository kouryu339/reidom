#pragma once

#include <juce_core/juce_core.h>

#include <cstddef>
#include <cstdint>
#include <vector>

#include "../audio/TrackEffects.h"
#include "../protocol/JsonUtils.h"

namespace reidom::engine {

inline constexpr std::size_t kMaxRealtimeTracks = 64;

struct Note {
    juce::String id;
    int pitch = 60;
    double start = 0.0;
    double duration = 1.0;
    int velocity = 90;
};

struct Clip {
    juce::String id;
    juce::String trackId;
    juce::String name;
    double start = 0.0;
    double duration = 4.0;
    std::vector<Note> notes;
};

struct Track {
    juce::String id;
    juce::String name;
    juce::String role = "unknown";
    juce::String instrument = "midi";
    juce::String color = "#6c7a91";
    bool mute = false;
    bool solo = false;
    bool arm = false;
    bool monitor = false;
    double volume = 0.85;
    double pan = 0.0;
    reidom::audio::TrackEffectSettings effects;
};

struct Transport {
    juce::String position = "001.1.1";
    double tempo = 120.0;
    bool loop = false;
    bool punch = false;
    bool metronome = true;
    bool sync = false;
    bool playing = false;
    bool recording = false;
    double loopStartBeat = 0.0;
    double loopEndBeat = 0.0;
};

struct ProjectState {
    juce::String id = newId("project");
    juce::String name = "Untitled MIDI";
    int64_t revision = 0;
    juce::String keySignature = "unknown";
    Transport transport;
    std::vector<Track> tracks;
    std::vector<Clip> clips;
    std::vector<juce::String> selectedTrackIds;
    std::vector<juce::String> selectedNoteIds;
    std::vector<juce::String> selectedClipIds;
    double selectionStartBeat = 0.0;
    double selectionEndBeat = 0.0;
};

struct CommandRecord {
    juce::String id;
    juce::String idempotencyKey;
    juce::String source;
    juce::String type;
    juce::String reason;
    int64_t baseRevision = 0;
    int64_t resultRevision = 0;
};

enum class BuiltinVoice {
    piano,
    lead,
    guitar,
    bass,
    pad,
    drums,
};

struct RenderNote {
    double startBeat = 0.0;
    double endBeat = 0.0;
    int pitch = 60;
    double gain = 0.5;
    double pan = 0.0;
    BuiltinVoice voice = BuiltinVoice::piano;
};

struct RenderTrack {
    juce::String id;
    bool audible = true;
    reidom::audio::TrackEffectSettings effects;
    std::vector<RenderNote> notes;
};

struct AudioSnapshot {
    double tempo = 120.0;
    double endBeat = 4.0;
    bool loop = false;
    bool metronome = false;
    double loopStartBeat = 0.0;
    double loopEndBeat = 0.0;
    std::vector<RenderTrack> tracks;
    struct RecordTarget {
        juce::String trackId;
        BuiltinVoice voice = BuiltinVoice::piano;
        double gain = 0.7;
        double pan = 0.0;
        bool monitor = false;
    };
    std::vector<RecordTarget> recordTargets;
};

struct ActiveMidiNote {
    juce::String trackId;
    int channel = 1;
    int pitch = 60;
    int velocity = 90;
    double startBeat = 0.0;
};

struct PendingMidiNote {
    juce::String trackId;
    int pitch = 60;
    int velocity = 90;
    double startBeat = 0.0;
    double durationBeats = 0.25;
};

struct LiveMidiNote {
    juce::String trackId;
    int channel = 1;
    int pitch = 60;
    double gain = 0.7;
    double pan = 0.0;
    double startedSeconds = 0.0;
    BuiltinVoice voice = BuiltinVoice::piano;
};

}  // namespace reidom::engine
