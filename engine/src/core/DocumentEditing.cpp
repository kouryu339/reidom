#include "ReidomEngine.h"
#include <algorithm>
#include <cmath>
#include <set>

namespace reidom::engine {
namespace {
void require(bool condition, const juce::String& message) { if (!condition) throw message; }

juce::var rule(const char* type, double minimum = 0, double maximum = 100000) {
    return object({{"type", type}, {"minimum", minimum}, {"maximum", maximum}});
}
juce::var schemaFor(const juce::String& target) {
    if (target == "song") return object({{"name", rule("string", 1, 120)}, {"tempo", rule("number", 20, 300)}});
    if (target == "tracks") return object({
        {"id", rule("string", 1, 80)}, {"name", rule("string", 1, 80)},
        {"instrument", object({{"type", "string"}, {"enum", array({"piano", "lead", "guitar", "bass", "pad", "drums"})}})},
        {"volume", rule("number", 0, 1.5)}, {"pan", rule("number", -1, 1)},
        {"mute", rule("boolean")}, {"solo", rule("boolean")}});
    if (target == "clips") return object({
        {"id", rule("string", 1, 80)}, {"track_id", rule("string", 1, 80)}, {"name", rule("string", 1, 80)},
        {"start_beats", rule("number")}, {"duration_beats", rule("number", 0.03125)}, {"notes", rule("array")}});
    return object({{"id", rule("string", 1, 80)}, {"pitch", rule("integer", 0, 127)},
        {"velocity", rule("integer", 1, 127)}, {"start_beats", rule("number")},
        {"duration_beats", rule("number", 0.03125)}});
}

void check(const juce::var& value, const juce::String& target, bool complete) {
    require(value.isObject(), target + ": expected object");
    const auto schema = schemaFor(target);
    for (const auto& field : value.getDynamicObject()->getProperties()) {
        const auto name = field.name.toString();
        const auto definition = property(schema, name.toRawUTF8());
        require(!definition.isVoid(), target + "/" + name + ": unknown field");
        const auto type = stringProperty(definition, "type");
        const auto& item = field.value;
        if (type == "string") {
            require(item.isString(), name + ": expected string");
            const auto length = item.toString().length();
            require(length >= doubleProperty(definition, "minimum", 1) && length <= doubleProperty(definition, "maximum", 80), name + ": invalid length");
            const auto choices = property(definition, "enum");
            if (choices.isArray()) require(choices.getArray()->contains(item), "unsupported instrument");
        } else if (type == "boolean") require(item.isBool(), name + ": expected boolean");
        else if (type == "array") require(item.isArray() && item.getArray()->size() <= 16384, name + ": expected array, max 16384");
        else {
            require(item.isInt() || item.isInt64() || item.isDouble(), name + ": expected number");
            const auto number = static_cast<double>(item);
            require(std::isfinite(number) && number >= doubleProperty(definition, "minimum") && number <= doubleProperty(definition, "maximum"), name + ": out of range");
            require(type != "integer" || std::floor(number) == number, name + ": expected integer");
        }
    }
    if (complete) {
        auto required = target == "tracks" ? juce::StringArray{"id", "name", "instrument"} :
            target == "clips" ? juce::StringArray{"id", "track_id", "name", "start_beats", "duration_beats", "notes"} :
            juce::StringArray{"id", "pitch", "velocity", "start_beats", "duration_beats"};
        for (const auto& key : required) require(!property(value, key.toRawUTF8()).isVoid(), target + "/" + key + ": required");
    }
}

void merge(juce::var& destination, const juce::var& fields) {
    for (const auto& field : fields.getDynamicObject()->getProperties())
        destination.getDynamicObject()->setProperty(field.name, field.value.clone());
}
}

juce::var ReidomEngine::editState() const {
    return object({{"mode", manualEditing_ ? "manual" : "ai"}, {"edit_epoch", editEpoch_}});
}

juce::var ReidomEngine::editMode(const juce::var& request) {
    if (stringProperty(request, "source") != "user") return error("mode_owner", "Only the user can switch edit mode");
    const auto mode = stringProperty(request, "mode");
    if (mode != "manual" && mode != "ai") return error("invalid_mode", "Expected manual or ai");
    if (recording_.load()) return error("recording_active", "Stop recording before switching mode");
    if (manualEditing_ != (mode == "manual")) { manualEditing_ = mode == "manual"; ++editEpoch_; }
    return ok(snapshotBundle());
}

juce::var ReidomEngine::document() const {
    const auto selection = selectionVar();
    std::vector<juce::var> tracks, clips;
    for (const auto& track : project_.tracks) tracks.push_back(object({
        {"id", track.id}, {"name", track.name}, {"instrument", track.instrument},
        {"volume", track.volume}, {"pan", track.pan}, {"mute", track.mute}, {"solo", track.solo}}));
    for (const auto& clip : project_.clips) {
        std::vector<juce::var> notes;
        for (const auto& note : clip.notes) notes.push_back(object({{"id", note.id}, {"pitch", note.pitch},
            {"velocity", note.velocity}, {"start_beats", note.start}, {"duration_beats", note.duration}}));
        clips.push_back(object({{"id", clip.id}, {"track_id", clip.trackId}, {"name", clip.name},
            {"start_beats", clip.start}, {"duration_beats", clip.duration}, {"notes", array(notes)}}));
    }
    return object({{"schema", "reidom-edit-document/v1"}, {"project_id", project_.id},
        {"revision", project_.revision}, {"edit_epoch", editEpoch_}, {"mode", manualEditing_ ? "manual" : "ai"},
        {"selection", object({
            {"track_ids", property(selection, "selected_track_ids")},
            {"clip_ids", property(selection, "selected_clip_ids")},
            {"note_ids", property(selection, "selected_note_ids")},
            {"range", property(selection, "range")}})},
        {"song", object({{"name", project_.name}, {"tempo", project_.transport.tempo}, {"tracks", array(tracks)}, {"clips", array(clips)}})}});
}

void ReidomEngine::publishDocument() const {
    const auto directory = juce::SystemStats::getEnvironmentVariable("REIDOM_DOCUMENT_DIR", "");
    if (directory.isEmpty()) return;
    const juce::File root(directory);
    require(root.createDirectory().wasOk(), "Cannot create project document directory");
    const auto current = root.getChildFile("current.json");
    const auto content = juce::JSON::toString(document(), false);
    if (current.loadFileAsString() != content) {
        juce::TemporaryFile temporary(current);
        require(temporary.getFile().replaceWithText(content) && temporary.overwriteTargetFileWithTemporary(), "Cannot publish current.json");
    }
    const auto schemaPath = root.getChildFile("schema.json");
    if (!schemaPath.existsAsFile()) {
        require(schemaPath.replaceWithText(juce::JSON::toString(object({
            {"song", schemaFor("song")}, {"tracks", schemaFor("tracks")},
            {"clips", schemaFor("clips")}, {"notes", schemaFor("notes")}}), false)), "Cannot publish schema.json");
    }
}

juce::var ReidomEngine::editDocument(const juce::var& request) {
    if (manualEditing_) return error("manual_edit_active", "AI writing is blocked during manual editing. Do not retry until user finishes.");
    if (stringProperty(request, "project_id") != project_.id ||
        static_cast<int64_t>(doubleProperty(request, "expected_revision", -1)) != project_.revision ||
        static_cast<int64_t>(doubleProperty(request, "edit_epoch", -1)) != editEpoch_)
        return error("revision_conflict", "Read current.json again: project, revision or edit epoch changed");
    const auto commandId = stringProperty(request, "request_id");
    if (commandId.isEmpty()) return error("request_id_required", "request_id is required");
    const auto duplicate = std::find_if(log_.begin(), log_.end(), [&](const auto& entry) { return entry.idempotencyKey == commandId; });
    if (duplicate != log_.end()) return error("duplicate_request", "This request_id already committed; read current.json");
    const auto changes = property(request, "changes");
    if (!changes.isArray() || changes.getArray()->isEmpty() || changes.getArray()->size() > 128)
        return error("invalid_changes", "changes requires 1..128 operations");
    auto song = property(document(), "song").clone();
    try {
        for (const auto& change : *changes.getArray()) {
            require(change.isObject(), "change must be object");
            for (const auto& field : change.getDynamicObject()->getProperties())
                require(juce::StringArray{"op", "target", "clip_id", "fields", "items", "ids"}.contains(field.name.toString()), "unknown change field " + field.name.toString());
            const auto target = stringProperty(change, "target");
            const auto op = stringProperty(change, "op");
            if (target == "song") {
                require(op == "merge", "song only supports merge");
                check(property(change, "fields"), "song", false);
                merge(song, property(change, "fields")); continue;
            }
            require(target == "tracks" || target == "clips" || target == "notes", "unknown target");
            auto collection = property(song, target.toRawUTF8());
            if (target == "notes") {
                auto clips = property(song, "clips");
                for (auto& clip : *clips.getArray())
                    if (stringProperty(clip, "id") == stringProperty(change, "clip_id")) collection = property(clip, "notes");
            }
            require(collection.isArray(), "unknown clip_id or collection");
            auto* items = collection.getArray();
            const auto incoming = property(change, op == "upsert" ? "items" : "ids");
            require((op == "upsert" || op == "remove") && incoming.isArray(), "Expected upsert/items or remove/ids");
            std::set<juce::String> batchIds;
            for (const auto& item : *incoming.getArray()) {
                const auto id = op == "upsert" ? stringProperty(item, "id") : item.toString();
                require(id.isNotEmpty() && batchIds.insert(id).second, "Missing or duplicate operation id");
                int index = -1;
                for (int i = 0; i < items->size(); ++i) if (stringProperty(items->getReference(i), "id") == id) { index = i; break; }
                if (op == "remove") { require(item.isString() && index >= 0, "Unknown remove id " + id); items->remove(index); }
                else {
                    check(item, target, index < 0);
                    if (index < 0) items->add(item.clone()); else merge(items->getReference(index), item);
                }
            }
        }
        ProjectState next = project_;
        next.name = stringProperty(song, "name"); next.transport.tempo = doubleProperty(song, "tempo");
        next.tracks.clear(); next.clips.clear();
        next.selectedTrackIds.clear(); next.selectedClipIds.clear(); next.selectedNoteIds.clear();
        auto tracks = property(song, "tracks"), clips = property(song, "clips");
        require(tracks.getArray()->size() <= 64 && clips.getArray()->size() <= 2048, "Track/clip budget exceeded");
        std::set<juce::String> trackIds, clipIds, noteIds;
        for (const auto& item : *tracks.getArray()) {
            // Existing imported instruments may retain their original engine preset names.
            const auto id = stringProperty(item, "id");
            require(trackIds.insert(id).second, "Duplicate track id");
            Track track;
            if (const auto* previous = findTrack(id)) track = *previous;
            else track.color = colorForTrack(static_cast<int>(next.tracks.size()));
            track.id = id; track.name = stringProperty(item, "name"); track.instrument = stringProperty(item, "instrument");
            track.role = track.instrument; track.volume = doubleProperty(item, "volume", 0.85); track.pan = doubleProperty(item, "pan");
            track.mute = boolProperty(item, "mute"); track.solo = boolProperty(item, "solo");
            next.tracks.push_back(track);
        }
        for (const auto& item : *clips.getArray()) {
            check(item, "clips", true);
            Clip clip;
            clip.id = stringProperty(item, "id"); clip.trackId = stringProperty(item, "track_id"); clip.name = stringProperty(item, "name");
            clip.start = doubleProperty(item, "start_beats"); clip.duration = doubleProperty(item, "duration_beats");
            require(clipIds.insert(clip.id).second && trackIds.contains(clip.trackId), "Duplicate clip or unknown track_id");
            const auto notes = property(item, "notes");
            for (const auto& value : *notes.getArray()) {
                check(value, "notes", true);
                Note note{stringProperty(value, "id"), intProperty(value, "pitch"), doubleProperty(value, "start_beats"), doubleProperty(value, "duration_beats"), intProperty(value, "velocity")};
                require(noteIds.insert(note.id).second && noteIds.size() <= 65536, "Duplicate note id or note budget exceeded");
                require(note.start >= clip.start && note.start < clip.start + clip.duration, "Note start is outside clip; use absolute beats");
                clip.notes.push_back(note);
            }
            next.clips.push_back(clip);
        }
        const auto before = project_;
        next.revision = project_.revision + 1;
        project_ = std::move(next);
        try { publishDocument(); } catch (...) { project_ = before; throw; }
        undo_.push_back(before); redo_.clear(); rebuildAudioSnapshot();
        log_.push_back({commandId, commandId, "ai", "document.edit", stringProperty(request, "reason"), before.revision, project_.revision});
        return ok(object({{"project_id", project_.id}, {"revision", project_.revision}, {"edit_epoch", editEpoch_}, {"applied", true}}));
    } catch (const juce::String& failure) {
        return error("document_rejected", failure + "; batch not saved, revision unchanged");
    }
}
}
