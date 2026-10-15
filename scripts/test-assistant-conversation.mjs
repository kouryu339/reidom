import assert from "node:assert/strict";
import { configureAssistant } from "../apps/studio-web/src/features/assistant/conversation.js";

class Conversation extends EventTarget {
  state = { conversationId: "conv_a", snapshotReceived: true, runtimeState: "waiting", revision: 1, records: [{ role: "user" }], modelUid: 1001 };
  emit(name, detail) { this.dispatchEvent(new CustomEvent(name, { detail })); }
}

const conversation = new Conversation();
let projectId = "song-a";
const calls = [];
let blockSave;
const archive = { archiveId: "conv_a", runtimeConversationId: "conv_a", createdAt: 1700000000000, updatedAt: 1700000001000, title: "测试会话", preview: "测试" };
const invoke = async (command, args) => {
  calls.push({ command, args });
  if (args?.action === "list") return { items: [archive] };
  if (args?.action === "save") { if (blockSave) await blockSave; return archive; }
  return { accepted: true };
};
const assistant = configureAssistant({ conversation, invoke, listen: async () => () => {}, getProjectId: () => projectId, onStateChange() {}, onError(message) { throw new Error(message); } });
conversation.emit("agent-conversation-ready", { conversationId: "conv_a" });
assert.equal(conversation.persistence.enabled, true);
assert.equal(conversation.persistence.showHistory, true);
assert.equal(conversation.persistence.binding.archiveId, "conv_a", "new chat is immediately available before the first message");
assert.equal(conversation.providerControls.showModelSwitcher, true);
assert.equal(conversation.providerControls.showImport, false, "provider editor stays in the model panel instead of crowding the header");
assert.equal(typeof conversation.providerControls.controller.configureProviders, "function");
assert.equal(conversation.transport.imageInput, undefined, "neither upload nor clipboard import is available");
const history = await conversation.persistence.controller.list({ search: "测试" });
assert.equal(history.items.length, 1);
assert.match(history.items[0].createdAt, /^2023-/);
await assistant.save();
assert.equal(calls.at(-1).args.projectId, "song-a");
assert.equal(conversation.persistence.binding.archiveId, "conv_a");
const count = calls.length;
await assistant.save();
assert.equal(calls.length, count, "unchanged conversation does not rewrite checkpoints");
conversation.state.runtimeState = "thinking";
await assistant.save();
assert.equal(calls.length, count, "do not checkpoint a running turn");
conversation.state.runtimeState = "waiting";
conversation.state.revision++;
let releaseSave;
blockSave = new Promise((resolve) => { releaseSave = resolve; });
const firstSave = assistant.save();
const staleSave = assistant.save();
projectId = "song-b";
conversation.state = { ...conversation.state, conversationId: "conv_b", revision: 1 };
conversation.emit("agent-conversation-ready", { conversationId: "conv_b" });
releaseSave();
await Promise.all([firstSave, staleSave]);
assert.equal(calls.filter((call) => call.args?.action === "save").length, 2, "a queued old save cannot target a new project");
assert.equal(conversation.persistence.binding.runtimeConversationId, "conv_b");
blockSave = null;
await conversation.persistence.controller.create();
assert.equal(calls.at(-1).args.projectId, "song-b");
await conversation.providerControls.controller.setConversationModel({ conversationId: "conv_b", modelUid: 1002 });
assert.deepEqual(calls.at(-1), { command: "ai_set_conversation_model", args: { conversationId: "conv_b", modelUid: 1002 } });
console.log("Assistant conversation integration passed: history, model controls, no images, project/save race guards.");
