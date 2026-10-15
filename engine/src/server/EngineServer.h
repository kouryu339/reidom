#pragma once

#include <cstdint>

namespace reidom::engine {

inline constexpr int kDefaultPort = 47120;
int runServer(int port, std::uint32_t parentPid);

}  // namespace reidom::engine
