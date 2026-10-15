#if defined(_WIN32)
#ifndef NOMINMAX
#define NOMINMAX
#endif
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#endif

#include "EngineServer.h"

#include <juce_core/juce_core.h>

#include <algorithm>
#include <array>
#include <atomic>
#include <iostream>
#include <memory>
#include <thread>

#include "../core/ReidomEngine.h"
#include "../protocol/JsonUtils.h"

namespace reidom::engine {

namespace {
constexpr int kMaxRequestBytes = 16 * 1024 * 1024;
}

juce::String readRequest(juce::StreamingSocket& socket) {
    juce::MemoryOutputStream stream;
    std::array<char, 8192> buffer{};
    while (stream.getDataSize() < kMaxRequestBytes) {
        if (socket.waitUntilReady(true, 5000) <= 0)
            break;
        const auto count = socket.read(buffer.data(), static_cast<int>(buffer.size()), false);
        if (count <= 0)
            break;
        stream.write(buffer.data(), static_cast<size_t>(count));
        if (std::find(buffer.begin(), buffer.begin() + count, '\n') != buffer.begin() + count)
            break;
    }
    return stream.toString().upToFirstOccurrenceOf("\n", false, false).trim();
}

bool writeResponse(juce::StreamingSocket& socket, const juce::String& response) {
    const auto* data = response.toRawUTF8();
    auto remaining = static_cast<int>(response.getNumBytesAsUTF8());
    while (remaining > 0) {
        if (socket.waitUntilReady(false, 5000) <= 0)
            return false;
        const auto written = socket.write(data, remaining);
        if (written <= 0)
            return false;
        data += written;
        remaining -= written;
    }
    return true;
}

int runServer(int port, uint32_t parentPid) {
    ReidomEngine engine;
    juce::StreamingSocket listener;
    if (!listener.createListener(port, "127.0.0.1")) {
        std::cerr << "Could not listen on 127.0.0.1:" << port << std::endl;
        return 2;
    }
    std::cout << "reidom-engine ready 127.0.0.1:" << port << std::endl;
    std::jthread parentWatcher;
    std::atomic_bool parentGone{false};
#if JUCE_WINDOWS
    if (parentPid != 0) {
        if (const auto parent = OpenProcess(SYNCHRONIZE, FALSE, parentPid)) {
            parentWatcher = std::jthread([parent, &parentGone](std::stop_token stopToken) {
                while (!stopToken.stop_requested()) {
                    if (WaitForSingleObject(parent, 250) == WAIT_OBJECT_0) {
                        parentGone.store(true);
                        break;
                    }
                }
                CloseHandle(parent);
            });
        }
    }
#else
    juce::ignoreUnused(parentPid);
#endif
    while (!engine.shouldStop() && !parentGone.load()) {
        if (listener.waitUntilReady(true, 250) <= 0)
            continue;
        std::unique_ptr<juce::StreamingSocket> client(listener.waitForNextConnection());
        if (client == nullptr)
            continue;
        juce::var request;
        const auto parseResult = juce::JSON::parse(readRequest(*client), request);
        auto response = parseResult.wasOk()
            ? engine.handle(request)
            : object({{"ok", false}, {"error", object({{"code", "invalid_json"}, {"message", parseResult.getErrorMessage()}})}});
        if (parseResult.wasOk() && boolProperty(response, "ok") && stringProperty(request, "method") != "engine.health")
            engine.handle(object({{"method", "document.publish"}}));
        const auto encoded = juce::JSON::toString(response, true) + "\n";
        writeResponse(*client, encoded);
        client->close();
    }
    listener.close();
    return 0;
}

}  // namespace reidom::engine
