#include "ReidomEngine.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <set>
#include <utility>

#include "../audio/DeviceSettings.h"
#include "../protocol/JsonUtils.h"

namespace reidom::engine {

ReidomEngine::ReidomEngine() {
    project_ = ProjectState{};
    rebuildAudioSnapshot();
    audioError_ = audioDeviceManager_.initialiseWithDefaultDevices(0, 2);
    if (audioError_.isEmpty())
        audioDeviceManager_.addAudioCallback(this);
    for (const auto& device : juce::MidiInput::getAvailableDevices()) {
        audioDeviceManager_.setMidiInputDeviceEnabled(device.identifier, true);
        audioDeviceManager_.addMidiInputDeviceCallback(device.identifier, this);
        midiInputIds_.push_back(device.identifier);
        midiInputNames_.push_back(device.name);
    }
}

ReidomEngine::~ReidomEngine() {
    for (const auto& identifier : midiInputIds_)
        audioDeviceManager_.removeMidiInputDeviceCallback(identifier, this);
    audioDeviceManager_.removeAudioCallback(this);
    audioDeviceManager_.closeAudioDevice();
}

juce::var ReidomEngine::handle(const juce::var& request) {
    std::scoped_lock lock(mutex_);
    const auto method = stringProperty(request, "method");
    if (method == "document.publish") {
        try { publishDocument(); return ok(object({{"published", true}})); }
        catch (const juce::String& failure) { return error("publication_failed", failure); }
    }
    if (method == "edit.mode") return editMode(request);
    if (method == "document.get") return ok(document());
    if (method == "document.edit") return editDocument(request);
    const auto source = stringProperty(request, "source", "user");
    const auto writesProject = method == "project.import_midi" || method == "project.import_json" ||
        method == "project.demo" || method == "history.undo" || method == "history.redo";
    if (writesProject && source != "restore" && source != "test" &&
        ((source == "ai") == manualEditing_))
        return error("edit_mode_conflict", manualEditing_ ? "Manual editing: AI writes are blocked" : "Enter manual edit mode first");
    if (method != "command.apply")
        drainRecordedNotes();
    if (method == "engine.health")
        return health();
    if (method == "devices.get")
        return ok(reidom::audio::describeDeviceSettings(audioDeviceManager_));
    if (method == "devices.configure")
        return configureDevices(request);
    if (method == "snapshot.get")
        return ok(snapshotBundle());
    if (method == "project.demo") {
        pushUndo();
        project_ = demoProject();
        redo_.clear();
        log_.clear();
        resetTransport();
        rebuildAudioSnapshot();
        return ok(snapshotBundle());
    }
    if (method == "project.new") {
        ++editEpoch_;
        pushUndo();
        project_ = ProjectState{};
        project_.name = stringProperty(request, "name", "Untitled Song").substring(0, 120);
        project_.transport.tempo = std::clamp(doubleProperty(request, "tempo", 120.0), 20.0, 300.0);
        redo_.clear();
        log_.clear();
        resetTransport();
        rebuildAudioSnapshot();
        return ok(snapshotBundle());
    }
    if (method == "project.import_midi")
        return importMidi(request);
    if (method == "project.export_midi")
        return exportMidi();
    if (method == "project.export_json")
        return exportProject();
    if (method == "project.import_json")
        return importProject(request);
    if (method == "project.render_wav")
        return renderWav();
    if (method == "command.apply")
        return applyCommand(property(request, "command"));
    if (method == "history.undo")
        return undo();
    if (method == "history.redo")
        return redo();
    if (method == "history.get")
        return ok(commandLog());
    if (method == "engine.shutdown") {
        shouldStop_.store(true);
        return ok(object({{"shutdown", true}}));
    }
    return error("unknown_method", "Unknown engine method: " + method);
}

bool ReidomEngine::shouldStop() const { return shouldStop_.load(); }

bool ReidomEngine::selfTest() {
    manualEditing_ = true;
    const auto demo = handle(object({{"method", "project.demo"}}));
    if (!boolProperty(demo, "ok"))
        return false;
    const auto trackId = project_.tracks.front().id;
    const auto selectionRevision = project_.revision;
    const auto selectionCommand = object({
        {"schema", "reidom-command/v2"},
        {"command_id", "self-test-track-selection"},
        {"idempotency_key", "self-test-track-selection"},
        {"project_id", project_.id},
        {"base_revision", selectionRevision},
        {"source", "system"},
        {"type", "selection.set"},
        {"payload", object({{"track_ids", array({trackId})}, {"note_ids", array({})}, {"clip_ids", array({})}})},
        {"reason", "Verify engine-owned track selection"},
        {"preview", false},
    });
    const auto selected = handle(object({{"method", "command.apply"}, {"command", selectionCommand}}));
    if (!boolProperty(selected, "ok") || project_.selectedTrackIds != std::vector<juce::String>{trackId})
        return false;
    const auto revision = project_.revision;
    const auto noteId = project_.clips.front().notes.front().id;
    const auto command = object({
        {"schema", "reidom-command/v2"},
        {"command_id", "self-test-transpose"},
        {"idempotency_key", "self-test-transpose"},
        {"project_id", project_.id},
        {"base_revision", revision},
        {"source", "system"},
        {"type", "notes.transpose"},
        {"payload", object({{"note_ids", array({noteId})}, {"semitones", 1}})},
        {"reason", "Verify transpose and undo"},
        {"preview", false},
    });
    const auto applied = handle(object({{"method", "command.apply"}, {"command", command}}));
    if (!boolProperty(applied, "ok") || project_.revision != revision + 1)
        return false;
    const auto undone = handle(object({{"method", "history.undo"}}));
    if (!boolProperty(undone, "ok") || project_.revision != revision + 2)
        return false;

    const auto applyTestCommand = [&](const juce::String& id, const juce::String& type,
                                      const juce::var& payload) {
        return handle(object({
            {"method", "command.apply"},
            {"command", object({
                {"schema", "reidom-command/v2"}, {"command_id", id},
                {"idempotency_key", id}, {"project_id", project_.id},
                {"base_revision", project_.revision}, {"source", "system"},
                {"type", type}, {"payload", payload},
                {"reason", "Engine self test"}, {"preview", false},
            })},
        }));
    };
    if (!boolProperty(applyTestCommand("self-test-arm", "routes.set_state",
            object({{"track_id", trackId}, {"state", object({{"arm", true}, {"monitor", true}})}})), "ok"))
        return false;
    const auto notesBeforeRecording = project_.clips.front().notes.size();
    if (!boolProperty(applyTestCommand("self-test-record-start", "transport.set_state",
            object({{"recording", true}, {"playing", true}})), "ok"))
        return false;
    playheadBeats_.store(2.0);
    handleIncomingMidiMessage(nullptr, juce::MidiMessage::noteOn(1, 65, static_cast<juce::uint8>(100)));
    playheadBeats_.store(3.0);
    handleIncomingMidiMessage(nullptr, juce::MidiMessage::noteOff(1, 65));
    handle(object({{"method", "snapshot.get"}}));
    if (!boolProperty(applyTestCommand("self-test-record-stop", "transport.set_state",
            object({{"recording", false}, {"playing", false}})), "ok"))
        return false;
    if (project_.clips.front().notes.size() != notesBeforeRecording + 1)
        return false;
    const auto undoRecording = handle(object({{"method", "history.undo"}}));
    if (!boolProperty(undoRecording, "ok") ||
        project_.clips.front().notes.size() != notesBeforeRecording)
        return false;
    const auto clipId = project_.clips.front().id;
    if (!boolProperty(applyTestCommand("self-test-clip-rename", "clips.rename",
            object({{"clip_ids", array({clipId})}, {"name", "Renamed Clip"}})), "ok") ||
        project_.clips.front().name != "Renamed Clip")
        return false;
    if (!boolProperty(applyTestCommand("self-test-clip-properties", "clips.set_properties",
            object({{"clip_ids", array({clipId})}, {"name", "Edited Clip"},
                    {"start_beats", 1.0}, {"duration_beats", 2.0}})), "ok") ||
        project_.clips.front().name != "Edited Clip" || project_.clips.front().start != 1.0 ||
        project_.clips.front().duration != 2.0)
        return false;
    if (!boolProperty(applyTestCommand("self-test-loop-range", "transport.set_state",
            object({{"loop", true}, {"loop_start_beats", 4.0}, {"loop_end_beats", 8.0}})), "ok") ||
        project_.transport.loopStartBeat != 4.0 || project_.transport.loopEndBeat != 8.0)
        return false;
    if (!boolProperty(applyTestCommand("self-test-track-effect", "effects.set_state",
            object({{"track_id", trackId}, {"effect", "eq"}, {"enabled", true},
                    {"parameters", object({{"low_gain_db", 3.5}, {"mid_gain_db", -1.0},
                                           {"high_gain_db", 2.0}})}})), "ok") ||
        !project_.tracks.front().effects.eqEnabled ||
        std::abs(project_.tracks.front().effects.lowGainDb - 3.5f) > 0.001f)
        return false;
    const auto undoEffect = handle(object({{"method", "history.undo"}}));
    if (!boolProperty(undoEffect, "ok") || project_.tracks.front().effects.eqEnabled)
        return false;
    const auto devices = handle(object({{"method", "devices.get"}}));
    return boolProperty(devices, "ok") &&
        stringProperty(property(devices, "result"), "schema") == "reidom-device-settings/v1";
}

juce::var ReidomEngine::health() const {
    auto deviceName = juce::String("unavailable");
    if (auto* device = audioDeviceManager_.getCurrentAudioDevice())
        deviceName = device->getName();
    std::vector<juce::var> midiInputs;
    for (const auto& name : midiInputNames_)
        midiInputs.push_back(name);
    return ok(object({
        {"schema", "reidom-engine-health/v1"},
        {"engine", "juce"},
        {"juce_version", juce::SystemStats::getJUCEVersion()},
        {"audio_device", deviceName},
        {"audio_error", audioError_},
        {"midi_inputs", array(midiInputs)},
        {"source_revision", project_.revision},
    }));
}

juce::var ReidomEngine::configureDevices(const juce::var& request) {
    const auto failure = reidom::audio::configureDeviceSettings(
        audioDeviceManager_,
        stringProperty(request, "output_device"),
        doubleProperty(request, "sample_rate"),
        intProperty(request, "buffer_size"),
        stringArrayProperty(request, "midi_input_ids"));
    if (failure.has_value()) {
        audioError_ = *failure;
        return error("device_configuration_failed", *failure);
    }
    audioError_.clear();
    if (auto* device = audioDeviceManager_.getCurrentAudioDevice())
        sampleRate_.store(device->getCurrentSampleRate());
    return ok(reidom::audio::describeDeviceSettings(audioDeviceManager_));
}

juce::var ReidomEngine::undo() {
    if (undo_.empty())
        return error("nothing_to_undo", "No project command to undo");
    redo_.push_back(project_);
    const auto nextRevision = project_.revision + 1;
    project_ = undo_.back();
    project_.revision = nextRevision;
    undo_.pop_back();
    resetTransport();
    rebuildAudioSnapshot();
    return ok(snapshotBundle());
}

juce::var ReidomEngine::redo() {
    if (redo_.empty())
        return error("nothing_to_redo", "No project command to redo");
    undo_.push_back(project_);
    const auto nextRevision = project_.revision + 1;
    project_ = redo_.back();
    project_.revision = nextRevision;
    redo_.pop_back();
    resetTransport();
    rebuildAudioSnapshot();
    return ok(snapshotBundle());
}

juce::var ReidomEngine::snapshotBundle() const {
    const auto selection = selectionVar();
    const auto project = projectVar(selection);
    const auto revision = project_.revision;
    return object({
        {"schema", "reidom-snapshot-bundle/v2"},
        {"snapshot_id", project_.id + ":" + juce::String(revision)},
        {"project_id", project_.id},
        {"source_revision", revision},
        {"source", object({{"owner", "juce-engine"}, {"implementation", "juce-9.0.0"}})},
        {"project_snapshot", object({
            {"schema", "reidom-project-snapshot/v2"},
            {"project_id", project_.id},
            {"name", project_.name},
            {"source_revision", revision},
            {"project", project},
            {"selection", selection},
            {"history", historyVar()},
        })},
        {"ui_snapshot", object({
            {"schema", "reidom-ui-snapshot/v2"},
            {"project_id", project_.id},
            {"source_revision", revision},
            {"project", project},
            {"selection", selection},
            {"history", historyVar()},
            {"capabilities", object({
                {"midi_import_export", true},
                {"midi_command_tools", true},
                {"command_log", true},
                {"undo_redo", true},
                {"audio_device", true},
                {"real_transport", true},
                {"project_persistence", true},
                {"wav_render", true},
                {"midi_input_recording", true},
                {"builtin_track_effects", true},
                {"plugin_hosting", false},
            })},
        })},
    });
}

}  // namespace reidom::engine
