#include "SpiDevice.hpp"

#ifdef __linux__

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/file.h>
#include <sys/stat.h>
#include <unistd.h>

#include <linux/spi/spidev.h>

SpiDevice::SpiDevice(const std::string& devPath, const uint32_t &speedHz,
            const uint8_t &mode, const uint8_t &bitsPerWord)
            : fd(-1),
              speed(speedHz),
              mode(mode),
              bits(bitsPerWord){
    
    fd = open(devPath.c_str(), O_RDWR | O_CLOEXEC);
    if (fd < 0) {
        throw std::runtime_error("Failed to open " + devPath + ": " + strerror(errno));
    }

    try {
    struct stat identity{};
    if (fstat(fd, &identity) != 0 || !S_ISCHR(identity.st_mode))
        throw std::runtime_error("SPI path is not a character device");
    // Cooperative process ownership covers the entire ADC/mux transaction,
    // not just individual kernel-serialized SPI transfers.
    if (flock(fd, LOCK_EX | LOCK_NB) != 0)
        throw std::runtime_error("SPI device is already owned by another cooperating process");
    if (ioctl(fd, SPI_IOC_WR_MODE, &mode) < 0)
        throw std::runtime_error("Failed to set SPI mode: " + std::string(strerror(errno)));

    if (ioctl(fd, SPI_IOC_WR_BITS_PER_WORD, &bits) < 0)
        throw std::runtime_error("Failed to set bits per word: " + std::string(strerror(errno)));

    if (ioctl(fd, SPI_IOC_WR_MAX_SPEED_HZ, &speed) < 0)
        throw std::runtime_error("Failed to set max speed: " + std::string(strerror(errno)));
    uint8_t observed_mode = 0, observed_bits = 0;
    if (ioctl(fd, SPI_IOC_RD_MODE, &observed_mode) < 0 || observed_mode != mode ||
        ioctl(fd, SPI_IOC_RD_BITS_PER_WORD, &observed_bits) < 0 || observed_bits != bits)
        throw std::runtime_error("SPI mode/word-size readback mismatch");
    } catch (...) {
        close(fd);
        fd = -1;
        throw;
    }
}

SpiDevice::~SpiDevice() {
    if (fd >= 0){ 
        close(fd);
    }
}

std::vector<uint8_t> SpiDevice::transfer(const std::vector<uint8_t>& tx) {
    if (tx.empty() || tx.size() > 4096) throw std::invalid_argument("SPI transfer length outside 1..4096 bytes");
    std::vector<uint8_t> rx(tx.size(), 0);

    struct spi_ioc_transfer tr = {};
    tr.tx_buf = reinterpret_cast<unsigned long>(tx.data());
    tr.rx_buf = reinterpret_cast<unsigned long>(rx.data());
    tr.len = tx.size();
    tr.speed_hz = speed;
    tr.bits_per_word = bits;

    if (ioctl(fd, SPI_IOC_MESSAGE(1), &tr) != static_cast<int>(tx.size())) {
        throw std::runtime_error("SPI transfer failed: " + std::string(strerror(errno)));
    }
    return rx;
}

uint32_t SpiDevice::getSpeedHz() const{
    return this->speed;
}

uint8_t SpiDevice::getMode() const{
    return this->mode;
}

uint8_t SpiDevice::getBitsPerWord() const{
    return this->bits;
}

#else

namespace {
[[noreturn]] void not_supported() {
    throw std::runtime_error("SpiDevice is supported only on Linux");
}
}  // namespace

SpiDevice::SpiDevice(const std::string&, const uint32_t&, const uint8_t&, const uint8_t&) { not_supported(); }
SpiDevice::~SpiDevice() = default;
std::vector<uint8_t> SpiDevice::transfer(const std::vector<uint8_t>&) { not_supported(); }
uint32_t SpiDevice::getSpeedHz() const { not_supported(); }
uint8_t SpiDevice::getMode() const { not_supported(); }
uint8_t SpiDevice::getBitsPerWord() const { not_supported(); }

#endif
