// Read-only admission diagnostic, never PREPARE/START.
#include "afe_capture.hpp"
#include <cerrno>
#include <fcntl.h>
#include <filesystem>
#include <iostream>
#include <sys/ioctl.h>
#include <unistd.h>
int main() {
  for (const auto base : {"b0020000", "b0040000", "b0060000"}) {
    std::error_code error;
    const auto path = std::filesystem::read_symlink(std::string("/sys/bus/platform/devices/")+base+".dma/driver", error);
    std::cout << base << " driver=" << path << " filename=" << path.filename() << " error=" << error.message() << '\n';
  }
  const int fd = open("/dev/daphne-afe-dma", O_RDONLY|O_CLOEXEC);
  daphne_afe_trigger_status t{};
  const int rc = ioctl(fd, DAPHNE_AFE_TRIGGER_STATUS, &t);
  std::cout << "fd=" << fd << " ioctl=" << std::hex << DAPHNE_AFE_TRIGGER_STATUS << std::dec
            << " size=" << sizeof(t) << " rc=" << rc << " errno=" << errno << " abi=" << t.abi << '\n';
  daphne_afe_dma_status s{};
  const int status_rc = ioctl(fd, DAPHNE_AFE_STATUS, &s);
  std::cout << "idle_status_rc=" << status_rc << " state=" << s.state << " allocated_bytes=" << s.allocated_bytes
            << " hardware_status=" << s.hardware_status << " hardware_error=" << s.hardware_error << '\n';
  for (unsigned r=0; r<3; ++r)
    std::cout << "route=" << r << " CR=" << s.dma_control[r] << " SR=" << s.dma_status[r] << '\n';
  close(fd);
  auto engine = daphne_dma::make_linux_afe_engine(64ULL<<20);
  std::cout << "engine supports_triggered=" << engine->supports_triggered() << " session_abi=" << engine->persistent_caps().abi << '\n';
}
