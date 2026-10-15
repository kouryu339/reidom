import { TauriConversationTransport } from "@agent-runtime/conversation-element/transport";

const PERSISTENCE_CONTRACT = "agent-conversation-persistence/v1";
const withDates = (archive) => ({
  ...archive,
  createdAt: typeof archive.createdAt === "number" ? new Date(archive.createdAt).toISOString() : archive.createdAt,
  updatedAt: typeof archive.updatedAt === "number" ? new Date(archive.updatedAt).toISOString() : archive.updatedAt,
});

export function configureAssistant({ conversation, invoke, listen, getProjectId, onStateChange, onError }) {
  let timer;
  let saving = null;
  let savedVersion = "";
  let boundProjectId = null;
  const version = () => `${conversation.state.conversationId}:${conversation.state.revision}:${conversation.state.records.length}:${conversation.state.modelUid}`;
  const history = (action, args = {}) => invoke("ai_conversation_history", { projectId: getProjectId(), action, ...args });
  const save = async () => {
    clearTimeout(timer);
    const state = conversation.state;
    if (boundProjectId !== getProjectId() || !state.snapshotReceived || state.runtimeState !== "waiting" || !state.records.length) return;
    if (saving) await saving;
    if (boundProjectId !== getProjectId() || state.conversationId !== conversation.state.conversationId || conversation.state.runtimeState !== "waiting") return;
    const currentVersion = version();
    if (savedVersion === currentVersion) return;
    const conversationId = conversation.state.conversationId;
    saving = history("save", { conversationId }).then((archive) => {
      savedVersion = currentVersion;
      if (conversation.state.conversationId === conversationId) {
        conversation.persistence = { ...conversation.persistence, binding: { archiveId: archive.archiveId, runtimeConversationId: conversationId } };
      }
      return withDates(archive);
    });
    try { return await saving; } finally { saving = null; }
  };

  const controller = {
    contract: PERSISTENCE_CONTRACT,
    async list(query = {}) {
      const projectId = getProjectId();
      const page = await history("list");
      if (projectId !== getProjectId()) throw new Error("作品已切换，请重新打开会话历史");
      const search = query.search?.toLowerCase();
      return { items: page.items.map(withDates).filter((item) => !search || `${item.title} ${item.preview}`.toLowerCase().includes(search)) };
    },
    async create() { const projectId = getProjectId(); clearTimeout(timer); if (saving) await saving; return history("create", { projectId }); },
    async restore({ archiveId }) { const projectId = getProjectId(); clearTimeout(timer); if (saving) await saving; return history("restore", { projectId, archiveId }); },
    async save({ runtimeConversationId, archiveId, title }) {
      return withDates(await history("save", { conversationId: runtimeConversationId, archiveId, title }));
    },
  };
  conversation.persistence = { enabled: true, showHistory: true, controller };
  const providerController = {
    getProviderDefinitions: () => invoke("ai_get_provider_definitions"),
    configureProviders: ({ input }) => invoke("ai_configure_providers", { input }),
    setConversationModel: ({ conversationId, modelUid }) => invoke("ai_set_conversation_model", { conversationId, modelUid }),
  };
  // Adding/editing providers stays inside the model panel, not a fourth header button.
  conversation.providerControls = { enabled: true, showModelSwitcher: true, showImport: false, controller: providerController };
  conversation.transport = new TauriConversationTransport({
    id: "reidom-tauri", invoke, listen,
    prepareArgs: () => ({ projectId: getProjectId() }),
    snapshotArgs: (conversationId) => ({ args: { conversationId } }),
    sendArgs: ({ conversationId, content, clientMessageId }) => ({ args: { conversationId, content, clientMessageId } }),
    commandArgs: (conversationId) => ({ args: { conversationId } }),
    permissionArgs: ({ conversationId, toolCallId, decision }) => ({ args: { conversationId, toolCallId, decision } }),
    // Deliberately omit imageImport: both upload and clipboard images are disabled.
  });
  conversation.addEventListener("agent-conversation-ready", ({ detail }) => {
    clearTimeout(timer);
    savedVersion = "";
    boundProjectId = getProjectId();
    const binding = conversation.persistence.binding;
    conversation.persistence = { ...conversation.persistence, binding: binding?.runtimeConversationId === detail.conversationId ? binding : { archiveId: detail.conversationId, runtimeConversationId: detail.conversationId } };
    // Runtime may have become available since the initial render.
    conversation.providerControls = { ...conversation.providerControls };
    conversation.persistedConversations = [];
  });
  conversation.addEventListener("agent-conversation-state-change", () => {
    onStateChange();
    clearTimeout(timer);
    if (conversation.state.runtimeState === "waiting") timer = setTimeout(() => save().catch((error) => onError(`会话历史保存失败：${String(error)}`)), 1200);
  });
  conversation.addEventListener("agent-conversation-error", ({ detail }) => onError(detail?.message || "会话连接失败"));
  return { save };
}
