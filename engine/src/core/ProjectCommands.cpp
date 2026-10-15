#include "ReidomEngine.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <utility>

#include "../audio/DeviceSettings.h"
#include "../protocol/JsonUtils.h"

namespace reidom::engine {

juce::var ReidomEngine::applyCommand(const juce::var& command) {
    if (stringProperty(command, "schema") != "reidom-command/v2")
        return error("invalid_schema", "Expected reidom-command/v2");
    if (stringProperty(command, "project_id") != project_.id)
        return error("project_mismatch", "Command project_id does not match the active project");
    if (boolProperty(command, "preview"))
        return error("preview_unsupported", "Preview commands are not applied by the engine");
    const auto idempotencyKey = stringProperty(command, "idempotency_key");
    if (idempotencyKey.isEmpty())
        return error("invalid_idempotency_key", "Command idempotency_key is required");
    const auto duplicate = std::find_if(log_.begin(), log_.end(), [&](const CommandRecord& item) {
        return item.idempotencyKey == idempotencyKey;
    });
    if (duplicate != log_.end())
        return ok(object({
            {"schema", "reidom-command-result/v2"},
            {"accepted", true},
            {"duplicate", true},
            {"command_id", duplicate->id},
            {"base_revision", duplicate->baseRevision},
            {"result_revision", duplicate->resultRevision},
            {"snapshot", snapshotBundle()},
        }));
    const auto baseRevision = static_cast<int64_t>(doubleProperty(command, "base_revision", -1));
    if (baseRevision != project_.revision)
        return error("revision_conflict", "Command base_revision does not match project revision");

    const auto type = stringProperty(command, "type");
    const auto payload = property(command, "payload");
    const auto source = stringProperty(command, "source");
    const auto viewing = type == "selection.set" || (type == "transport.set_state" &&
        property(payload, "tempo").isVoid() && property(payload, "bpm").isVoid() &&
        property(payload, "loop").isVoid() && property(payload, "loop_start_beats").isVoid() &&
        property(payload, "loop_end_beats").isVoid() && property(payload, "metronome").isVoid() &&
        !boolProperty(payload, "recording"));
    if (source == "ai")
        return error("use_document_edit", "AI must use the schema-validated document.edit entry point");
    if (!viewing && !manualEditing_)
        return error("edit_mode_conflict", "Enter manual edit mode to change the song");
    justFinalizedRecording_ = false;
    const auto startingRecording = type == "transport.set_state" && !project_.transport.recording &&
        !property(payload, "recording").isVoid() && boolProperty(payload, "recording");
    if (startingRecording) {
        recordingStartState_ = project_;
        recordedInTake_ = false;
    }
    if (type == "transport.set_state" && project_.transport.recording &&
        !property(payload, "recording").isVoid() && !boolProperty(payload, "recording")) {
        finishActiveMidiNotes(playheadBeats_.load());
        drainRecordedNotes();
    }
    const auto before = project_;
    if (const auto failure = mutate(type, payload); failure.has_value()) {
        project_ = before;
        return error("command_rejected", *failure);
    }

    const auto transportPersistent = type == "transport.set_state" &&
        (!property(payload, "tempo").isVoid() || !property(payload, "bpm").isVoid() ||
         !property(payload, "loop").isVoid() || !property(payload, "loop_start_beats").isVoid() ||
         !property(payload, "loop_end_beats").isVoid() || !property(payload, "metronome").isVoid());
    const auto transient = type == "selection.set" ||
        (type == "transport.set_state" && !justFinalizedRecording_ && !transportPersistent);
    if (justFinalizedRecording_ && recordingStartState_.has_value())
        undo_.push_back(*recordingStartState_);
    else if (!transient)
        undo_.push_back(before);
    if (!transient) { redo_.clear(); ++project_.revision; }
    if (!transient)
        rebuildAudioSnapshot();
    log_.push_back({
        stringProperty(command, "command_id", newId("cmd")),
        idempotencyKey,
        stringProperty(command, "source", "unknown"),
        type,
        stringProperty(command, "reason"),
        baseRevision,
        project_.revision,
    });
    if (justFinalizedRecording_)
        recordingStartState_.reset();
    return ok(object({
        {"schema", "reidom-command-result/v2"},
        {"accepted", true},
        {"command_id", log_.back().id},
        {"base_revision", baseRevision},
        {"result_revision", project_.revision},
        {"snapshot", snapshotBundle()},
    }));
}

std::optional<juce::String> ReidomEngine::mutate(const juce::String& type, const juce::var& payload) {
    if (type == "selection.set") {
        project_.selectedTrackIds = stringArrayProperty(payload, "track_ids");
        project_.selectedNoteIds = stringArrayProperty(payload, "note_ids");
        project_.selectedClipIds = stringArrayProperty(payload, "clip_ids");
        const auto range = property(payload, "range");
        if (!range.isVoid()) {
            project_.selectionStartBeat = std::max(0.0, doubleProperty(range, "start_beats"));
            project_.selectionEndBeat = std::max(
                project_.selectionStartBeat, doubleProperty(range, "end_beats", project_.selectionStartBeat));
        }
        return std::nullopt;
    }
    if (type == "transport.set_state") {
        if (!property(payload, "position").isVoid()) {
            project_.transport.position = stringProperty(payload, "position");
            playheadBeats_.store(beatsFromPosition(project_.transport.position));
        }
        if (!property(payload, "tempo").isVoid() || !property(payload, "bpm").isVoid())
            project_.transport.tempo = std::clamp(
                doubleProperty(payload, "tempo", doubleProperty(payload, "bpm", project_.transport.tempo)),
                20.0, 300.0);
        assignBool(payload, "loop", project_.transport.loop);
        assignBool(payload, "punch", project_.transport.punch);
        assignBool(payload, "metronome", project_.transport.metronome);
        assignBool(payload, "sync", project_.transport.sync);
        assignBool(payload, "playing", project_.transport.playing);
        const auto wasRecording = project_.transport.recording;
        assignBool(payload, "recording", project_.transport.recording);
        if (!property(payload, "loop_start_beats").isVoid())
            project_.transport.loopStartBeat = std::max(0.0,
                doubleProperty(payload, "loop_start_beats"));
        if (!property(payload, "loop_end_beats").isVoid())
            project_.transport.loopEndBeat = std::max(
                project_.transport.loopStartBeat + 0.25,
                doubleProperty(payload, "loop_end_beats"));
        if (wasRecording && !project_.transport.recording)
            justFinalizedRecording_ = recordedInTake_;
        recording_.store(project_.transport.recording);
        playing_.store(project_.transport.playing);
        rebuildAudioSnapshot();
        return std::nullopt;
    }
    if (type == "routes.set_state")
        return mutateRoute(payload);
    if (type == "effects.set_state")
        return mutateEffects(payload);
    if (type == "arrangement.add_track")
        return addArrangementTrack(payload);
    if (type.startsWith("tracks."))
        return mutateTracks(type, payload);
    if (type.startsWith("notes."))
        return mutateNotes(type, payload);
    if (type.startsWith("clips."))
        return mutateClips(type, payload);
    return "Unsupported command type: " + type;
}

std::optional<juce::String> ReidomEngine::addArrangementTrack(const juce::var& payload) {
    const auto* events = property(payload, "notes").getArray();
    if (events == nullptr || events->isEmpty())
        return "Arrangement track requires at least one note";
    if (events->size() > 4096)
        return "Arrangement track is limited to 4096 notes";

    Track track;
    track.id = newId("track");
    track.name = stringProperty(payload, "name", "AI Arrangement").substring(0, 80);
    track.role = stringProperty(payload, "role", "accompaniment").substring(0, 40);
    track.instrument = stringProperty(payload, "instrument", "piano").substring(0, 80);
    track.color = stringProperty(payload, "color", "#7c6ee6");

    Clip clip;
    clip.id = newId("clip");
    clip.trackId = track.id;
    clip.name = stringProperty(payload, "clip_name", track.name + " Part").substring(0, 80);
    clip.start = std::numeric_limits<double>::max();
    double end = 0.0;
    for (const auto& event : *events) {
        const auto bar = std::max(1, intProperty(event, "bar", 1));
        const auto beat = std::clamp(doubleProperty(event, "b", 1.0), 1.0, 4.99999);
        const auto start = std::max(0.0, doubleProperty(
            event, "start_beats", (bar - 1) * 4.0 + beat - 1.0));
        const auto duration = std::max(
            0.03125, doubleProperty(event, "duration_beats", doubleProperty(event, "l", 0.25)));
        Note note{
            newId("note"),
            std::clamp(intProperty(event, "pitch", intProperty(event, "n", 60)), 0, 127),
            start,
            duration,
            std::clamp(intProperty(event, "velocity", intProperty(event, "v", 90)), 1, 127),
        };
        clip.start = std::min(clip.start, start);
        end = std::max(end, start + duration);
        clip.notes.push_back(note);
    }
    if (clip.start == std::numeric_limits<double>::max())
        clip.start = 0.0;
    clip.duration = std::max(0.25, end - clip.start);
    project_.tracks.push_back(track);
    project_.clips.push_back(clip);
    project_.selectedNoteIds.clear();
    project_.selectedClipIds = {clip.id};
    return std::nullopt;
}

std::optional<juce::String> ReidomEngine::mutateRoute(const juce::var& payload) {
    const auto trackId = stringProperty(payload, "track_id");
    const auto state = property(payload, "state");
    auto* track = findTrack(trackId);
    if (track == nullptr)
        return "Unknown track: " + trackId;
    assignBool(state, "mute", track->mute);
    assignBool(state, "solo", track->solo);
    assignBool(state, "arm", track->arm);
    assignBool(state, "monitor", track->monitor);
    if (!property(state, "volume").isVoid())
        track->volume = std::clamp(doubleProperty(state, "volume", track->volume), 0.0, 1.5);
    if (!property(state, "pan").isVoid())
        track->pan = std::clamp(doubleProperty(state, "pan", track->pan), -1.0, 1.0);
    return std::nullopt;
}

std::optional<juce::String> ReidomEngine::mutateEffects(const juce::var& payload) {
    const auto trackId = stringProperty(payload, "track_id");
    auto* track = findTrack(trackId);
    if (track == nullptr)
        return "Unknown track: " + trackId;
    const auto effect = stringProperty(payload, "effect").toLowerCase();
    const auto parameters = property(payload, "parameters");
    const auto enabled = property(payload, "enabled");
    if (effect == "eq") {
        if (!enabled.isVoid())
            track->effects.eqEnabled = boolProperty(payload, "enabled", track->effects.eqEnabled);
        track->effects.lowGainDb = static_cast<float>(std::clamp(
            doubleProperty(parameters, "low_gain_db", track->effects.lowGainDb), -12.0, 12.0));
        track->effects.midGainDb = static_cast<float>(std::clamp(
            doubleProperty(parameters, "mid_gain_db", track->effects.midGainDb), -12.0, 12.0));
        track->effects.highGainDb = static_cast<float>(std::clamp(
            doubleProperty(parameters, "high_gain_db", track->effects.highGainDb), -12.0, 12.0));
        return std::nullopt;
    }
    if (effect == "compressor") {
        if (!enabled.isVoid())
            track->effects.compressorEnabled = boolProperty(
                payload, "enabled", track->effects.compressorEnabled);
        track->effects.compressorThresholdDb = static_cast<float>(std::clamp(
            doubleProperty(parameters, "threshold_db", track->effects.compressorThresholdDb),
            -48.0, 0.0));
        track->effects.compressorRatio = static_cast<float>(std::clamp(
            doubleProperty(parameters, "ratio", track->effects.compressorRatio), 1.0, 12.0));
        return std::nullopt;
    }
    if (effect == "delay") {
        if (!enabled.isVoid())
            track->effects.delayEnabled = boolProperty(payload, "enabled", track->effects.delayEnabled);
        track->effects.delayTimeMs = static_cast<float>(std::clamp(
            doubleProperty(parameters, "time_ms", track->effects.delayTimeMs), 20.0, 1500.0));
        track->effects.delayFeedback = static_cast<float>(std::clamp(
            doubleProperty(parameters, "feedback", track->effects.delayFeedback), 0.0, 0.82));
        track->effects.delayMix = static_cast<float>(std::clamp(
            doubleProperty(parameters, "mix", track->effects.delayMix), 0.0, 0.65));
        return std::nullopt;
    }
    if (effect == "reverb") {
        if (!enabled.isVoid())
            track->effects.reverbEnabled = boolProperty(payload, "enabled", track->effects.reverbEnabled);
        track->effects.reverbRoomSize = static_cast<float>(std::clamp(
            doubleProperty(parameters, "room_size", track->effects.reverbRoomSize), 0.0, 1.0));
        track->effects.reverbMix = static_cast<float>(std::clamp(
            doubleProperty(parameters, "mix", track->effects.reverbMix), 0.0, 0.65));
        return std::nullopt;
    }
    return "Unknown built-in effect: " + effect;
}

std::optional<juce::String> ReidomEngine::mutateTracks(const juce::String& type, const juce::var& payload) {
    if (type == "tracks.add") {
        Track track;
        track.id = newId("track");
        track.name = stringProperty(payload, "name", "新建轨道").substring(0, 80);
        track.role = stringProperty(payload, "role", "midi").substring(0, 40);
        track.instrument = stringProperty(payload, "instrument", "piano").substring(0, 80);
        track.color = stringProperty(payload, "color", colorForTrack(static_cast<int>(project_.tracks.size())));
        project_.tracks.push_back(track);
        Clip clip;
        clip.id = newId("clip");
        clip.trackId = track.id;
        clip.name = track.name + " 片段";
        clip.start = std::max(0.0, doubleProperty(payload, "start_beats", playheadBeats_.load()));
        clip.duration = std::max(0.25, doubleProperty(payload, "duration_beats", 4.0));
        project_.clips.push_back(std::move(clip));
        project_.selectedTrackIds = {track.id};
        project_.selectedClipIds.clear();
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    const auto trackId = stringProperty(payload, "track_id");
    const auto found = std::ranges::find(project_.tracks, trackId, &Track::id);
    if (found == project_.tracks.end())
        return "Unknown track: " + trackId;
    if (type == "tracks.delete") {
        std::erase_if(project_.clips, [&](const Clip& clip) { return clip.trackId == trackId; });
        project_.tracks.erase(found);
        project_.selectedTrackIds.clear();
        project_.selectedClipIds.clear();
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    if (type == "tracks.rename") {
        const auto name = stringProperty(payload, "name").trim().substring(0, 80);
        if (name.isEmpty())
            return "Track name is required";
        found->name = name;
        return std::nullopt;
    }
    if (type == "tracks.set_instrument") {
        found->instrument = stringProperty(payload, "instrument", "piano").substring(0, 80);
        found->role = stringProperty(payload, "role", found->role).substring(0, 40);
        return std::nullopt;
    }
    if (type == "tracks.reorder") {
        const auto oldIndex = static_cast<int>(std::distance(project_.tracks.begin(), found));
        const auto newIndex = std::clamp(intProperty(payload, "index", oldIndex), 0,
                                         static_cast<int>(project_.tracks.size()) - 1);
        auto track = *found;
        project_.tracks.erase(found);
        project_.tracks.insert(project_.tracks.begin() + newIndex, std::move(track));
        return std::nullopt;
    }
    return "Unsupported track command: " + type;
}

std::optional<juce::String> ReidomEngine::mutateNotes(const juce::String& type, const juce::var& payload) {
    auto ids = stringArrayProperty(payload, "note_ids");
    if (type == "notes.add") {
        auto* clip = findClip(stringProperty(payload, "clip_id"));
        if (clip == nullptr)
            return "Unknown clip";
        Note note{
            newId("note"),
            std::clamp(intProperty(payload, "pitch", 60), 0, 127),
            std::max(0.0, doubleProperty(payload, "start_beats")),
            std::max(0.03125, doubleProperty(payload, "duration_beats", 1.0)),
            std::clamp(intProperty(payload, "velocity", 90), 1, 127),
        };
        clip->notes.push_back(note);
        project_.selectedNoteIds = {note.id};
        project_.selectedClipIds.clear();
        return std::nullopt;
    }
    if (type == "notes.batch_update") {
        const auto* edits = property(payload, "edits").getArray();
        if (edits == nullptr || edits->isEmpty())
            return "Batch update requires edits";
        if (edits->size() > 4096)
            return "Batch update is limited to 4096 notes";
        std::set<juce::String> matched;
        for (auto& clip : project_.clips) {
            for (auto& note : clip.notes) {
                for (const auto& edit : *edits) {
                    const auto noteId = stringProperty(
                        edit, "note_id", stringProperty(edit, "noteId"));
                    if (note.id != noteId)
                        continue;
                    note.start = std::max(0.0, note.start + doubleProperty(
                        edit, "delta_beats", doubleProperty(edit, "deltaBeats")));
                    if (!property(edit, "velocity").isVoid())
                        note.velocity = std::clamp(
                            intProperty(edit, "velocity", note.velocity), 1, 127);
                    matched.insert(note.id);
                }
            }
        }
        if (matched.empty())
            return "Batch update did not match any notes";
        project_.selectedNoteIds.assign(matched.begin(), matched.end());
        project_.selectedClipIds.clear();
        return std::nullopt;
    }
    if (ids.empty())
        ids = project_.selectedNoteIds;
    if (ids.empty())
        return "Command requires note_ids or an active note selection";
    const std::set<juce::String> selected(ids.begin(), ids.end());

    if (type == "notes.delete") {
        for (auto& clip : project_.clips)
            std::erase_if(clip.notes, [&](const Note& note) { return selected.contains(note.id); });
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    if (type == "notes.duplicate") {
        const auto offset = doubleProperty(payload, "delta_beats", 1.0);
        std::vector<juce::String> created;
        for (auto& clip : project_.clips) {
            const auto original = clip.notes;
            for (const auto& note : original) {
                if (!selected.contains(note.id))
                    continue;
                auto copy = note;
                copy.id = newId("note");
                copy.start = std::max(0.0, copy.start + offset);
                clip.notes.push_back(copy);
                created.push_back(copy.id);
            }
        }
        project_.selectedNoteIds = created;
        return std::nullopt;
    }

    bool matched = false;
    for (auto& clip : project_.clips) {
        for (auto& note : clip.notes) {
            if (!selected.contains(note.id))
                continue;
            matched = true;
            if (type == "notes.transpose")
                note.pitch = std::clamp(note.pitch + intProperty(payload, "semitones"), 0, 127);
            else if (type == "notes.move") {
                note.start = std::max(0.0, note.start + doubleProperty(payload, "delta_beats"));
                note.pitch = std::clamp(note.pitch + intProperty(payload, "delta_pitch"), 0, 127);
            } else if (type == "notes.resize")
                note.duration = std::max(0.03125, note.duration + doubleProperty(payload, "delta_beats"));
            else if (type == "notes.velocity")
                note.velocity = std::clamp(intProperty(payload, "velocity", note.velocity), 1, 127);
            else if (type == "notes.quantize") {
                const auto grid = std::max(0.03125, doubleProperty(payload, "grid_beats", 0.25));
                note.start = std::round(note.start / grid) * grid;
            } else
                return "Unsupported note command: " + type;
        }
    }
    return matched ? std::nullopt : std::optional<juce::String>("No matching notes");
}

std::optional<juce::String> ReidomEngine::mutateClips(const juce::String& type, const juce::var& payload) {
    if (type == "clips.create") {
        const auto trackId = stringProperty(payload, "track_id");
        if (findTrack(trackId) == nullptr)
            return "Unknown track: " + trackId;
        Clip clip;
        clip.id = newId("clip");
        clip.trackId = trackId;
        clip.name = stringProperty(payload, "name", "MIDI 片段").substring(0, 80);
        clip.start = std::max(0.0, doubleProperty(payload, "start_beats"));
        clip.duration = std::max(0.25, doubleProperty(payload, "duration_beats", 4.0));
        project_.clips.push_back(clip);
        project_.selectedClipIds = {clip.id};
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    if (type == "clips.rename") {
        const auto ids = stringArrayProperty(payload, "clip_ids");
        if (ids.size() != 1)
            return "Clip rename requires exactly one clip";
        auto* clip = findClip(ids.front());
        if (clip == nullptr)
            return "Unknown clip: " + ids.front();
        const auto name = stringProperty(payload, "name").trim().substring(0, 80);
        if (name.isEmpty())
            return "Clip name is required";
        clip->name = name;
        project_.selectedClipIds = {clip->id};
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    if (type == "clips.set_properties") {
        const auto ids = stringArrayProperty(payload, "clip_ids");
        if (ids.size() != 1)
            return "Clip properties require exactly one clip";
        auto* clip = findClip(ids.front());
        if (clip == nullptr)
            return "Unknown clip: " + ids.front();
        const auto name = stringProperty(payload, "name", clip->name).trim().substring(0, 80);
        if (name.isEmpty())
            return "Clip name is required";
        const auto oldStart = clip->start;
        const auto newStart = std::max(0.0, doubleProperty(payload, "start_beats", oldStart));
        clip->name = name;
        clip->start = newStart;
        clip->duration = std::max(0.25, doubleProperty(payload, "duration_beats", clip->duration));
        for (auto& note : clip->notes)
            note.start = std::max(newStart, note.start + newStart - oldStart);
        project_.selectedClipIds = {clip->id};
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    auto ids = stringArrayProperty(payload, "clip_ids");
    if (ids.empty())
        ids = project_.selectedClipIds;
    if (ids.empty())
        return "Command requires clip_ids or an active clip selection";
    const std::set<juce::String> selected(ids.begin(), ids.end());
    const auto delta = doubleProperty(payload, "delta_beats");
    if (type == "clips.duplicate") {
        const auto original = project_.clips;
        std::vector<juce::String> created;
        for (const auto& clip : original) {
            if (!selected.contains(clip.id))
                continue;
            auto copy = clip;
            copy.id = newId("clip");
            copy.name += " Copy";
            copy.start = std::max(0.0, copy.start + (delta == 0.0 ? 4.0 : delta));
            for (auto& note : copy.notes) {
                note.id = newId("note");
                note.start = std::max(0.0, note.start + (delta == 0.0 ? 4.0 : delta));
            }
            project_.clips.push_back(copy);
            created.push_back(copy.id);
        }
        project_.selectedClipIds = created;
        project_.selectedNoteIds.clear();
        return std::nullopt;
    }
    if (type == "clips.delete") {
        const auto before = project_.clips.size();
        std::erase_if(project_.clips, [&](const Clip& clip) { return selected.contains(clip.id); });
        project_.selectedClipIds.clear();
        project_.selectedNoteIds.clear();
        return project_.clips.size() < before
            ? std::nullopt
            : std::optional<juce::String>("No matching clips");
    }
    if (type == "clips.split") {
        const auto splitBeat = std::max(0.0, doubleProperty(payload, "at_beats", playheadBeats_.load()));
        std::vector<Clip> created;
        for (auto& clip : project_.clips) {
            if (!selected.contains(clip.id) || splitBeat <= clip.start || splitBeat >= clip.start + clip.duration)
                continue;
            const auto oldEnd = clip.start + clip.duration;
            Clip right = clip;
            right.id = newId("clip");
            right.name += " B";
            right.start = splitBeat;
            right.duration = oldEnd - splitBeat;
            right.notes.clear();
            std::vector<Note> leftNotes;
            for (const auto& note : clip.notes) {
                const auto noteEnd = note.start + note.duration;
                if (note.start < splitBeat) {
                    auto left = note;
                    left.duration = std::max(0.03125, std::min(noteEnd, splitBeat) - note.start);
                    leftNotes.push_back(left);
                }
                if (noteEnd > splitBeat) {
                    auto rightNote = note;
                    rightNote.id = newId("note");
                    rightNote.start = std::max(note.start, splitBeat);
                    rightNote.duration = std::max(0.03125, noteEnd - rightNote.start);
                    right.notes.push_back(rightNote);
                }
            }
            clip.notes = std::move(leftNotes);
            clip.duration = splitBeat - clip.start;
            created.push_back(std::move(right));
        }
        if (created.empty())
            return "Split point must be inside a selected clip";
        project_.selectedClipIds.clear();
        for (auto& clip : created) {
            project_.selectedClipIds.push_back(clip.id);
            project_.clips.push_back(std::move(clip));
        }
        return std::nullopt;
    }
    bool matched = false;
    for (auto& clip : project_.clips) {
        if (!selected.contains(clip.id))
            continue;
        matched = true;
        if (type == "clips.move") {
            clip.start = std::max(0.0, clip.start + delta);
            for (auto& note : clip.notes)
                note.start = std::max(0.0, note.start + delta);
            const auto targetTrackId = stringProperty(payload, "target_track_id");
            if (targetTrackId.isNotEmpty() && findTrack(targetTrackId) != nullptr)
                clip.trackId = targetTrackId;
        } else if (type == "clips.resize")
            clip.duration = std::max(0.03125, clip.duration + delta);
        else if (type == "clips.trim_start") {
            const auto oldEnd = clip.start + clip.duration;
            clip.start = std::clamp(clip.start + delta, 0.0, oldEnd - 0.03125);
            clip.duration = oldEnd - clip.start;
        }
        else
            return "Unsupported clip command: " + type;
    }
    return matched ? std::nullopt : std::optional<juce::String>("No matching clips");
}

}  // namespace reidom::engine
