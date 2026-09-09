#pragma once
#include <condition_variable>
#include <cstddef>
#include <functional>
#include <mutex>
#include <queue>
#include <stdexcept>
#include <thread>
#include <utility>

namespace daphne_sc {
// Exactly one hardware worker. The router never blocks when submitting work
// or collecting replies, and therefore can serve bookkeeping during Configure.
template<class Reply> class SerialExecutor {
 public:
  using Publish = std::function<void(Reply)>;
  using Work = std::function<void(const Publish&)>;
  explicit SerialExecutor(size_t capacity = 16) : capacity_(capacity) {
    if (!capacity_) throw std::invalid_argument("Executor queue capacity must be positive");
    worker_ = std::thread([this] { run(); });
  }
  ~SerialExecutor() { stop(); }
  SerialExecutor(const SerialExecutor&) = delete;
  SerialExecutor& operator=(const SerialExecutor&) = delete;
  bool try_submit(Work work) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (stopping_ || work_.size() == capacity_) return false;
    work_.push(std::move(work));
    changed_.notify_all();
    return true;
  }
  bool try_take(Reply& reply) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (replies_.empty()) return false;
    reply = std::move(replies_.front());
    replies_.pop();
    changed_.notify_all();
    return true;
  }
  void stop() {
    {
      std::lock_guard<std::mutex> lock(mutex_);
      stopping_ = true;
      while (!work_.empty()) work_.pop(); // Never start queued writes after shutdown.
      changed_.notify_all();
    }
    if (worker_.joinable()) worker_.join();
  }
  size_t unhandled_errors() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return errors_;
  }
 private:
  void run() {
    const Publish publish = [this](Reply reply) {
      std::unique_lock<std::mutex> lock(mutex_);
      changed_.wait(lock, [&] { return stopping_ || replies_.size() < capacity_; });
      if (stopping_) throw std::runtime_error("Executor is stopping");
      replies_.push(std::move(reply));
      changed_.notify_all();
    };
    for (;;) {
      Work work;
      {
        std::unique_lock<std::mutex> lock(mutex_);
        changed_.wait(lock, [&] { return stopping_ || !work_.empty(); });
        if (stopping_) return;
        work = std::move(work_.front());
        work_.pop();
      }
      try { work(publish); }
      catch (...) { std::lock_guard<std::mutex> lock(mutex_); ++errors_; }
    }
  }
  const size_t capacity_;
  mutable std::mutex mutex_;
  std::condition_variable changed_;
  std::queue<Work> work_;
  std::queue<Reply> replies_;
  bool stopping_ = false;
  size_t errors_ = 0;
  std::thread worker_;
};
}
