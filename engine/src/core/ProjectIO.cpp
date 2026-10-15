#include "ReidomEngine.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <utility>

#include "../audio/DeviceSettings.h"
#include "../protocol/JsonUtils.h"

namespace reidom::engine {

juce::var ReidomEngine::importMidi(const juce::var& request) {
    juce::MemoryBlock bytes;
    juce::MemoryOutputStream decoded(bytes, false);
    if (!juce::Base64::convertFromBase64(decoded, stringProperty(request, "data_base64")))
        return error("invalid_midi", "data_base64 is invalid");
    juce::MemoryInputStream stream(bytes, false);
    juce::MidiFile midi;
    if (!midi.readFrom(stream))
        return error("invalid_midi", "JUCE could not read the MIDI file");
    const auto ticksPerQuarter = midi.getTimeFormat() > 0 ? midi.getTimeFormat() : 960;
    ProjectState imported;
    imported.name = stringProperty(request, "file_name", "Imported MIDI");
    imported.revision = 1;
    imported.transport.tempo = 120.0;
    for (int trackIndex = 0; trackIndex < midi.getNumTracks(); ++trackIndex) {
        const auto* sequence = midi.getTrack(trackIndex);
        if (sequence == nullptr)
            continue;
        Track track;
        track.id = "track-" + juce::String(trackIndex + 1);
        track.name = "MIDI " + juce::String(trackIndex + 1);
        track.color = colorForTrack(trackIndex);
        Clip clip;
        clip.id = newId("clip");
        clip.trackId = track.id;
        clip.name = track.name;
        for (int eventIndex = 0; eventIndex < sequence->getNumEvents(); ++eventIndex) {
            const auto* holder = sequence->getEventPointer(eventIndex);
            if (holder == nullptr || !holder->message.isNoteOn())
                continue;
            const auto start = holder->message.getTimeStamp() / ticksPerQuarter;
            auto duration = 0.25;
            if (holder->noteOffObject != nullptr)
                duration = std::max(0.03125,
                    (holder->noteOffObject->message.getTimeStamp() - holder->message.getTimeStamp()) /
                        ticksPerQuarter);
            clip.notes.push_back({
                newId("note"), holder->message.getNoteNumber(), start, duration,
                static_cast<int>(holder->message.getVelocity() * 127.0f),
            });
            clip.duration = std::max(clip.duration, start + duration);
        }
        if (!clip.notes.empty()) {
            imported.tracks.push_back(track);
            imported.clips.push_back(clip);
        }
    }
    if (imported.tracks.empty())
        return error("empty_midi", "MIDI file contains no note tracks");
    pushUndo();
    project_ = std::move(imported);
    redo_.clear();
    log_.clear();
    resetTransport();
    rebuildAudioSnapshot();
    return ok(snapshotBundle());
}

juce::var ReidomEngine::exportMidi() const {
    juce::MidiFile midi;
    constexpr int ticksPerQuarter = 960;
    midi.setTicksPerQuarterNote(ticksPerQuarter);
    for (const auto& track : project_.tracks) {
        juce::MidiMessageSequence sequence;
        sequence.addEvent(juce::MidiMessage::textMetaEvent(3, track.name));
        for (const auto& clip : project_.clips) {
            if (clip.trackId != track.id)
                continue;
            for (const auto& note : clip.notes) {
                sequence.addEvent(juce::MidiMessage::noteOn(1, note.pitch,
                    static_cast<juce::uint8>(note.velocity)), note.start * ticksPerQuarter);
                sequence.addEvent(juce::MidiMessage::noteOff(1, note.pitch),
                    (note.start + note.duration) * ticksPerQuarter);
            }
        }
        sequence.updateMatchedPairs();
        midi.addTrack(sequence);
    }
    juce::MemoryOutputStream stream;
    if (!midi.writeTo(stream))
        return error("midi_export_failed", "JUCE could not encode the project MIDI");
    return ok(object({
        {"file_name", project_.name + ".mid"},
        {"data_base64", juce::Base64::toBase64(
            stream.getMemoryBlock().getData(), stream.getMemoryBlock().getSize())},
    }));
}

juce::var ReidomEngine::exportProject() const {
    return ok(object({
        {"schema", "reidom-project-file/v1"},
        {"file_name", project_.name + ".reidom"},
        {"project", projectVar(selectionVar())},
    }));
}

juce::var ReidomEngine::importProject(const juce::var& request) {
    const auto value = property(request, "project");
    if (stringProperty(value, "schema") != "reidom-project/v1")
        return error("invalid_project", "Expected reidom-project/v1");
    ProjectState loaded;
    loaded.id = stringProperty(value, "project_id", newId("project"));
    loaded.name = stringProperty(value, "name", "Untitled Song").substring(0, 120);
    loaded.revision = std::max<int64_t>(1, static_cast<int64_t>(doubleProperty(value, "revision", 1)));
    loaded.keySignature = stringProperty(value, "key_signature", "unknown");
    const auto transport = property(value, "transport");
    auto tempoFromMap = 120.0;
    if (const auto* tempoMap = property(value, "tempo_map").getArray(); tempoMap != nullptr && !tempoMap->isEmpty())
        tempoFromMap = doubleProperty(tempoMap->getFirst(), "bpm", tempoFromMap);
    loaded.transport.tempo = std::clamp(
        doubleProperty(transport, "tempo", tempoFromMap),
        20.0, 300.0);
    loaded.transport.loop = boolProperty(transport, "loop");
    loaded.transport.metronome = boolProperty(transport, "metronome", true);
    loaded.transport.loopStartBeat = std::max(0.0,
        doubleProperty(transport, "loop_start_beats"));
    loaded.transport.loopEndBeat = std::max(
        loaded.transport.loopStartBeat,
        doubleProperty(transport, "loop_end_beats"));
    if (const auto* tracks = property(value, "tracks").getArray()) {
        for (const auto& item : *tracks) {
            Track track;
            track.id = stringProperty(item, "track_id", newId("track"));
            track.name = stringProperty(item, "name", "MIDI Track").substring(0, 80);
            track.role = stringProperty(item, "role", "midi").substring(0, 40);
            track.instrument = stringProperty(item, "instrument_ref", "piano").substring(0, 80);
            track.color = stringProperty(item, "color", "#6c7a91");
            track.mute = boolProperty(item, "mute");
            track.solo = boolProperty(item, "solo");
            track.arm = boolProperty(item, "arm");
            track.monitor = boolProperty(item, "monitor");
            track.volume = std::clamp(doubleProperty(item, "volume", 0.85), 0.0, 1.5);
            track.pan = std::clamp(doubleProperty(item, "pan", 0.0), -1.0, 1.0);
            readEffectSettings(track.effects, property(item, "effects"));
            loaded.tracks.push_back(std::move(track));
        }
    }
    if (const auto* clips = property(value, "clips").getArray()) {
        for (const auto& item : *clips) {
            Clip clip;
            clip.id = stringProperty(item, "clip_id", newId("clip"));
            clip.trackId = stringProperty(item, "track_id");
            clip.name = stringProperty(item, "name", "MIDI Clip").substring(0, 80);
            clip.start = std::max(0.0, doubleProperty(item, "start_beats"));
            clip.duration = std::max(0.03125, doubleProperty(item, "duration_beats", 4.0));
            if (const auto* notes = property(item, "notes").getArray()) {
                for (const auto& note : *notes) {
                    clip.notes.push_back({
                        stringProperty(note, "note_id", newId("note")),
                        std::clamp(intProperty(note, "pitch", 60), 0, 127),
                        std::max(0.0, doubleProperty(note, "start_beats")),
                        std::max(0.03125, doubleProperty(note, "duration_beats", 1.0)),
                        std::clamp(intProperty(note, "velocity", 90), 1, 127),
                    });
                }
            }
            if (std::ranges::find(loaded.tracks, clip.trackId, &Track::id) != loaded.tracks.end())
                loaded.clips.push_back(std::move(clip));
        }
    }
    const auto selection = property(value, "selection");
    loaded.selectedTrackIds = stringArrayProperty(selection, "selected_track_ids");
    loaded.selectedNoteIds = stringArrayProperty(selection, "selected_note_ids");
    loaded.selectedClipIds = stringArrayProperty(selection, "selected_clip_ids");
    const auto range = property(selection, "range");
    loaded.selectionStartBeat = std::max(0.0, doubleProperty(range, "start_beats"));
    loaded.selectionEndBeat = std::max(
        loaded.selectionStartBeat, doubleProperty(range, "end_beats", loaded.selectionStartBeat));
    pushUndo();
    ++editEpoch_;
    project_ = std::move(loaded);
    redo_.clear();
    log_.clear();
    resetTransport();
    rebuildAudioSnapshot();
    return ok(snapshotBundle());
}

juce::var ReidomEngine::renderWav() const {
    const auto snapshot = audioSnapshot_.load();
    const auto hasAudibleNotes = snapshot && std::ranges::any_of(
        snapshot->tracks, [](const RenderTrack& track) {
            return track.audible && !track.notes.empty();
        });
    if (!hasAudibleNotes)
        return error("empty_project", "The project has no audible MIDI notes");
    constexpr double sampleRate = 44100.0;
    constexpr int renderBlockSize = 512;
    const auto seconds = std::clamp(
        snapshot->endBeat * 60.0 / snapshot->tempo + 2.0, 0.5, 600.0);
    const auto sampleCount = static_cast<int>(std::ceil(seconds * sampleRate));
    juce::AudioBuffer<float> buffer(2, sampleCount);
    juce::AudioBuffer<float> scratch(2, renderBlockSize);
    buffer.clear();
    for (const auto& track : snapshot->tracks) {
        if (!track.audible || track.notes.empty())
            continue;
        reidom::audio::TrackEffectProcessor processor;
        processor.prepare(sampleRate);
        processor.configure(track.effects);
        for (int blockStart = 0; blockStart < sampleCount; blockStart += renderBlockSize) {
            const auto blockLength = std::min(renderBlockSize, sampleCount - blockStart);
            scratch.clear();
            for (const auto& note : track.notes) {
                const auto noteStart = std::clamp(static_cast<int>(
                    note.startBeat * 60.0 / snapshot->tempo * sampleRate), 0, sampleCount);
                const auto noteEnd = std::clamp(static_cast<int>(
                    note.endBeat * 60.0 / snapshot->tempo * sampleRate), noteStart, sampleCount);
                const auto overlapStart = std::max(blockStart, noteStart);
                const auto overlapEnd = std::min(blockStart + blockLength, noteEnd);
                if (overlapStart >= overlapEnd)
                    continue;
                const auto durationSeconds =
                    (note.endBeat - note.startBeat) * 60.0 / snapshot->tempo;
                for (int sample = overlapStart; sample < overlapEnd; ++sample) {
                    const auto elapsed = (sample - noteStart) / sampleRate;
                    const auto value = oscillator(
                        note.voice, note.pitch, elapsed, durationSeconds) * note.gain * 0.16;
                    const auto localSample = sample - blockStart;
                    scratch.addSample(0, localSample, static_cast<float>(
                        value * std::sqrt((1.0 - note.pan) * 0.5)));
                    scratch.addSample(1, localSample, static_cast<float>(
                        value * std::sqrt((1.0 + note.pan) * 0.5)));
                }
            }
            for (int offset = 0; offset < blockLength; ++offset) {
                auto left = scratch.getSample(0, offset);
                auto right = scratch.getSample(1, offset);
                processor.processSample(left, right);
                buffer.addSample(0, blockStart + offset, left);
                buffer.addSample(1, blockStart + offset, right);
            }
        }
    }
    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
        for (int sample = 0; sample < buffer.getNumSamples(); ++sample)
            buffer.setSample(channel, sample, std::tanh(buffer.getSample(channel, sample)));
    juce::MemoryBlock bytes;
    std::unique_ptr<juce::OutputStream> stream = std::make_unique<juce::MemoryOutputStream>(bytes, false);
    juce::WavAudioFormat format;
    auto writer = format.createWriterFor(
        stream,
        juce::AudioFormatWriterOptions{}.withSampleRate(sampleRate).withNumChannels(2).withBitsPerSample(24));
    if (!writer || !writer->writeFromAudioSampleBuffer(buffer, 0, sampleCount))
        return error("wav_render_failed", "JUCE could not render the WAV file");
    writer.reset();
    return ok(object({
        {"file_name", project_.name + ".wav"},
        {"data_base64", juce::Base64::toBase64(bytes.getData(), bytes.getSize())},
        {"duration_seconds", seconds},
    }));
}

juce::var ReidomEngine::projectVar(const juce::var& selection) const {
    std::vector<juce::var> tracks;
    for (const auto& track : project_.tracks) {
        std::vector<juce::var> clipIds;
        for (const auto& clip : project_.clips)
            if (clip.trackId == track.id)
                clipIds.push_back(clip.id);
        tracks.push_back(object({
            {"track_id", track.id}, {"name", track.name}, {"type", "midi"},
            {"role", track.role}, {"color", track.color}, {"mute", track.mute},
            {"solo", track.solo}, {"arm", track.arm}, {"monitor", track.monitor},
            {"volume", track.volume}, {"pan", track.pan},
            {"effects", effectSettingsVar(track.effects)},
            {"instrument_ref", track.instrument}, {"clip_ids", array(clipIds)},
        }));
    }
    std::vector<juce::var> clips;
    for (const auto& clip : project_.clips)
        clips.push_back(clipVar(clip));
    return object({
        {"schema", "reidom-project/v1"}, {"project_id", project_.id},
        {"name", project_.name}, {"revision", project_.revision},
        {"editing", editState()},
        {"key_signature", project_.keySignature},
        {"tempo_map", array({object({{"start_beats", 0}, {"bpm", project_.transport.tempo}})})},
        {"time_signatures", array({object({
            {"start_beats", 0}, {"numerator", 4}, {"denominator", 4},
        })})},
        {"transport", transportVar()}, {"tracks", array(tracks)}, {"clips", array(clips)},
        {"sections", array({
            object({{"section_id", "section-1"}, {"name", juce::String::fromUTF8("前奏")}, {"start_beats", 0}, {"duration_beats", 8}}),
            object({{"section_id", "section-2"}, {"name", juce::String::fromUTF8("主歌")}, {"start_beats", 8}, {"duration_beats", 8}}),
            object({{"section_id", "section-3"}, {"name", juce::String::fromUTF8("副歌")}, {"start_beats", 16}, {"duration_beats", 8}}),
            object({{"section_id", "section-4"}, {"name", juce::String::fromUTF8("尾奏")}, {"start_beats", 24}, {"duration_beats", 8}}),
        })},
        {"markers", array({})}, {"selection", selection},
        {"undo_stack", array({})}, {"redo_stack", array({})},
    });
}

juce::var ReidomEngine::selectionVar() const {
    std::vector<juce::var> tracks;
    for (const auto& track : project_.tracks) {
        std::vector<juce::var> notes;
        for (const auto& clip : project_.clips) {
            if (clip.trackId != track.id)
                continue;
            for (const auto& note : clip.notes)
                notes.push_back(noteVar(note, track.id, clip.id));
        }
        tracks.push_back(object({
            {"track_id", track.id}, {"name", track.name}, {"role", track.role},
            {"instrument", track.instrument}, {"notes", array(notes)},
        }));
    }
    std::vector<juce::var> noteIds;
    for (const auto& id : project_.selectedNoteIds)
        noteIds.push_back(id);
    std::vector<juce::var> clipIds;
    for (const auto& id : project_.selectedClipIds)
        clipIds.push_back(id);
    std::vector<juce::var> trackIds;
    for (const auto& id : project_.selectedTrackIds)
        trackIds.push_back(id);
    return object({
        {"schema", "reidom-midi-selection/v1"},
        {"selection_id", "selection-" + juce::String(project_.revision)},
        {"project_id", project_.id}, {"revision", project_.revision},
        {"source", object({{"engine", "juce"}, {"project_id", project_.id}})},
        {"range", object({{"start_beats", project_.selectionStartBeat}, {"end_beats", project_.selectionEndBeat}})},
        {"tempo", project_.transport.tempo},
        {"time_signature", object({{"numerator", 4}, {"denominator", 4}})},
        {"tracks", array(tracks)}, {"selected_note_ids", array(noteIds)},
        {"selected_clip_ids", array(clipIds)}, {"selected_track_ids", array(trackIds)},
    });
}

juce::var ReidomEngine::clipVar(const Clip& clip) const {
    std::vector<juce::var> notes;
    for (const auto& note : clip.notes)
        notes.push_back(noteVar(note, clip.trackId, clip.id));
    return object({
        {"clip_id", clip.id}, {"track_id", clip.trackId}, {"name", clip.name},
        {"start_beats", clip.start}, {"duration_beats", clip.duration},
        {"loop_enabled", false},
        {"source_range", object({{"start_beats", clip.start}, {"end_beats", clip.start + clip.duration}})},
        {"notes", array(notes)},
    });
}

juce::var ReidomEngine::noteVar(const Note& note, const juce::String& trackId,
                         const juce::String& clipId) {
    return object({
        {"note_id", note.id}, {"track_id", trackId}, {"clip_id", clipId},
        {"pitch", note.pitch}, {"start_beats", note.start},
        {"duration_beats", note.duration}, {"velocity", note.velocity},
    });
}

juce::var ReidomEngine::transportVar() const {
    return object({
        {"position", positionFromBeats(playheadBeats_.load())}, {"tempo", project_.transport.tempo},
        {"loop", project_.transport.loop}, {"punch", project_.transport.punch},
        {"loop_start_beats", project_.transport.loopStartBeat},
        {"loop_end_beats", project_.transport.loopEndBeat},
        {"metronome", project_.transport.metronome}, {"sync", project_.transport.sync},
        {"playing", playing_.load()}, {"recording", recording_.load()},
    });
}

juce::var ReidomEngine::historyVar() const {
    return object({
        {"undo_available", !undo_.empty()}, {"redo_available", !redo_.empty()},
        {"undo_depth", static_cast<int>(undo_.size())},
        {"redo_depth", static_cast<int>(redo_.size())},
    });
}

juce::var ReidomEngine::commandLog() const {
    std::vector<juce::var> entries;
    int index = 1;
    for (const auto& record : log_) {
        entries.push_back(object({
            {"index", index++}, {"command_id", record.id}, {"source", record.source},
            {"type", record.type}, {"reason", record.reason},
            {"base_revision", record.baseRevision}, {"result_revision", record.resultRevision},
        }));
    }
    return object({
        {"project_id", project_.id}, {"revision", project_.revision},
        {"entries", array(entries)},
    });
}

double ReidomEngine::projectEnd() const {
    double result = 24.0;
    for (const auto& clip : project_.clips)
        result = std::max(result, clip.start + clip.duration);
    return result;
}

Track* ReidomEngine::findTrack(const juce::String& id) {
    const auto found = std::ranges::find(project_.tracks, id, &Track::id);
    return found == project_.tracks.end() ? nullptr : &*found;
}

Clip* ReidomEngine::findClip(const juce::String& id) {
    const auto found = std::ranges::find(project_.clips, id, &Clip::id);
    return found == project_.clips.end() ? nullptr : &*found;
}

void ReidomEngine::assignBool(const juce::var& source, const char* name, bool& destination) {
    if (!property(source, name).isVoid())
        destination = boolProperty(source, name, destination);
}

void ReidomEngine::pushUndo() {
    undo_.push_back(project_);
    redo_.clear();
}

juce::String ReidomEngine::colorForTrack(int index) {
    static const std::array colours{"#b8f547", "#45c6ef", "#ffae43", "#d58cff"};
    return colours[static_cast<size_t>(index) % colours.size()];
}

ProjectState ReidomEngine::demoProject() {
    ProjectState project;
    project.name = juce::String::fromUTF8("午夜公路 · 编曲草图");
    project.revision = 1;
    project.keySignature = "A minor";
    project.transport.tempo = 96.0;
    project.transport.loop = true;

    const std::array ids{"lead", "chords", "guitar", "bass", "drums", "pad"};
    const std::array names{
        juce::String::fromUTF8("主旋律 · 柔和合成器"),
        juce::String::fromUTF8("钢琴 · 和弦进行"),
        juce::String::fromUTF8("电吉他 · 间奏"),
        juce::String::fromUTF8("电贝斯 · 根音线条"),
        juce::String::fromUTF8("鼓组 · 基础律动"),
        juce::String::fromUTF8("氛围铺底 · 长音"),
    };
    const std::array roles{"lead", "harmony", "guitar", "bass", "drums", "pad"};
    const std::array instruments{
        "soft-synth-lead", "piano", "electric-guitar", "electric-bass", "drum-kit", "warm-pad"};

    for (int index = 0; index < static_cast<int>(ids.size()); ++index) {
        Track track;
        track.id = ids[static_cast<size_t>(index)];
        track.name = names[static_cast<size_t>(index)];
        track.role = roles[static_cast<size_t>(index)];
        track.instrument = instruments[static_cast<size_t>(index)];
        track.color = colorForTrack(index);
        track.volume = index == 4 ? 0.76 : index == 5 ? 0.58 : 0.72;
        track.pan = index == 2 ? 0.22 : index == 5 ? -0.18 : 0.0;
        if (index == 0) {
            track.effects.delayEnabled = true;
            track.effects.delayMix = 0.09f;
            track.effects.reverbEnabled = true;
            track.effects.reverbMix = 0.1f;
        } else if (index == 2) {
            track.effects.delayEnabled = true;
            track.effects.delayTimeMs = 310.0f;
            track.effects.delayMix = 0.1f;
        } else if (index == 3 || index == 4) {
            track.effects.compressorEnabled = true;
            track.effects.compressorThresholdDb = index == 4 ? -14.0f : -18.0f;
            track.effects.compressorRatio = index == 4 ? 4.0f : 3.0f;
            track.effects.eqEnabled = true;
            track.effects.lowGainDb = index == 3 ? 2.0f : 1.0f;
        } else if (index == 5) {
            track.effects.eqEnabled = true;
            track.effects.highGainDb = -2.0f;
            track.effects.reverbEnabled = true;
            track.effects.reverbRoomSize = 0.62f;
            track.effects.reverbMix = 0.2f;
        }
        project.tracks.push_back(track);

        Clip clip;
        clip.id = track.id + "-clip-1";
        clip.trackId = track.id;
        clip.name = track.name;
        clip.start = index == 2 ? 16.0 : 0.0;
        clip.duration = index == 2 ? 8.0 : 32.0;
        if (index == 2)
            clip.name = juce::String::fromUTF8("间奏吉他");
        const auto addNote = [&](int pitch, double start, double duration, int velocity) {
            clip.notes.push_back({newId("note"), pitch, start, duration, velocity});
        };

        if (index == 0) {
            const std::array melody{69, 72, 76, 74, 72, 69, 67, 64, 69, 72, 76, 79, 76, 74, 72, 69};
            for (int step = 0; step < 32; ++step)
                addNote(melody[static_cast<size_t>(step % melody.size())], step, step % 4 == 3 ? 0.9 : 0.72,
                        82 + (step % 5) * 3);
        } else if (index == 1 || index == 5) {
            const std::array<std::array<int, 4>, 4> chords{{
                {{57, 60, 64, 67}}, {{53, 57, 60, 64}}, {{55, 59, 62, 65}}, {{48, 52, 55, 62}},
            }};
            for (int chordIndex = 0; chordIndex < 8; ++chordIndex) {
                const auto& chord = chords[static_cast<size_t>(chordIndex % chords.size())];
                for (const auto pitch : chord)
                    addNote(pitch + (index == 5 ? 12 : 0), chordIndex * 4.0, index == 5 ? 7.8 : 3.8,
                            index == 5 ? 54 : 74 + chordIndex % 3 * 3);
            }
        } else if (index == 2) {
            const std::array<std::array<int, 4>, 4> shapes{{
                {{64, 67, 72, 76}}, {{64, 69, 72, 77}}, {{62, 65, 67, 71}}, {{62, 67, 72, 76}},
            }};
            for (int chordIndex = 0; chordIndex < 2; ++chordIndex) {
                const auto& shape = shapes[static_cast<size_t>(chordIndex % shapes.size())];
                for (int step = 0; step < 8; ++step)
                    addNote(shape[static_cast<size_t>(step % shape.size())], 16.0 + chordIndex * 4.0 + step * 0.5,
                            0.38, 66 + (step % 4) * 4);
            }
        } else if (index == 3) {
            const std::array roots{45, 41, 43, 36};
            for (int chordIndex = 0; chordIndex < 8; ++chordIndex) {
                const auto root = roots[static_cast<size_t>(chordIndex % roots.size())];
                addNote(root, chordIndex * 4.0, 1.7, 88);
                addNote(root + 7, chordIndex * 4.0 + 2.0, 1.55, 78);
            }
        } else {
            for (int beat = 0; beat < 32; ++beat) {
                addNote(42, beat, 0.18, beat % 4 == 0 ? 86 : 66);
                addNote(42, beat + 0.5, 0.16, 58);
                if (beat % 4 == 0 || beat % 4 == 2)
                    addNote(36, beat, 0.22, beat % 4 == 0 ? 102 : 88);
                if (beat % 4 == 1 || beat % 4 == 3)
                    addNote(38, beat, 0.2, 96);
            }
        }
        project.clips.push_back(std::move(clip));
    }
    return project;
}

juce::var ReidomEngine::ok(juce::var result) {
    return object({{"ok", true}, {"result", std::move(result)}});
}

juce::var ReidomEngine::error(const juce::String& code, const juce::String& message) {
    return object({
        {"ok", false},
        {"error", object({{"code", code}, {"message", message}})},
    });
}

}  // namespace reidom::engine
