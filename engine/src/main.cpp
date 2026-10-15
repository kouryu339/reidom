#include <juce_core/juce_core.h>

#include <cstdint>
#include <iostream>

#include "core/ReidomEngine.h"
#include "server/EngineServer.h"

int main(int argc, char* argv[]) {
    juce::ScopedJuceInitialiser_GUI juceInitialiser;
    if (argc > 1 && juce::String(argv[1]) == "--self-test") {
        reidom::engine::ReidomEngine engine;
        const auto passed = engine.selfTest();
        std::cout << (passed ? "reidom-engine self-test passed" : "reidom-engine self-test failed") << std::endl;
        return passed ? 0 : 1;
    }
    auto port = reidom::engine::kDefaultPort;
    uint32_t parentPid = 0;
    for (int index = 1; index + 1 < argc; index += 2) {
        const auto option = juce::String(argv[index]);
        if (option == "--port")
            port = juce::String(argv[index + 1]).getIntValue();
        else if (option == "--parent-pid")
            parentPid = static_cast<uint32_t>(juce::String(argv[index + 1]).getLargeIntValue());
    }
    return reidom::engine::runServer(port, parentPid);
}
