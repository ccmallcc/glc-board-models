// 板端基准测试模板 —— W1/W2 要测"板上耗时"时照这个改。
//
// 板端计时最容易犯的三个错，这个模板都规避了：
//   ① 只跑一次就报数（受频率爬升/缓存冷启动影响）-> 先 warm-up，再多轮取统计量
//   ② 报"总耗时"而不报"单次/单符号"      -> 两者都打，且把工作量一起打出来
//   ③ 把编译器的常数折叠当成被测逻辑      -> volatile / 累加回写，防止整个循环被优化掉
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <vector>

using Clock = std::chrono::steady_clock;

// 被测对象：把这里换成你真正要测的东西（例如 rANS 编码一个符号块）
static std::uint64_t workload(std::uint64_t n) {
    std::uint64_t acc = 0;
    for (std::uint64_t i = 0; i < n; ++i) {
        acc = acc * 6364136223846793005ULL + 1442695040888963407ULL;
        acc ^= (acc >> 29);
    }
    return acc;
}

static double ms_since(Clock::time_point t0) {
    return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

int main() {
    constexpr std::uint64_t N = 200000;   // 每次调用的工作量（当成"符号数"）
    constexpr int WARMUP = 3;
    constexpr int REPS   = 21;

    std::printf("=== board-side benchmark template ===\n");
    std::printf("workload = %llu per call\n\n", (unsigned long long)N);

    std::uint64_t sink = 0;

    // ---- ① warm-up：让频率爬升、让缓存热起来 ----
    for (int i = 0; i < WARMUP; ++i) sink += workload(N);

    // ---- ② 多轮测量，存下来 ----
    std::vector<double> t;
    t.reserve(REPS);
    for (int i = 0; i < REPS; ++i) {
        auto t0 = Clock::now();
        sink += workload(N);
        t.push_back(ms_since(t0));
    }

    std::sort(t.begin(), t.end());
    double sum = 0;
    for (double v : t) sum += v;
    const double mean = sum / t.size();
    const double med  = t[t.size() / 2];

    std::printf("reps=%zu  warmup=%d\n", t.size(), WARMUP);
    std::printf("  min    = %8.3f ms\n", t.front());
    std::printf("  median = %8.3f ms\n", med);
    std::printf("  mean   = %8.3f ms\n", mean);
    std::printf("  max    = %8.3f ms\n", t.back());
    std::printf("\n");
    // ---- ③ 同一口径换算成"每次/每符号" ----
    std::printf("  per call  = %8.2f ns      (median)\n", med * 1e6);
    std::printf("  per unit  = %8.2f ns      (median / %llu)\n",
                med * 1e6 / (double)N, (unsigned long long)N);
    std::printf("\n(sink=%llu, 防止循环被优化掉)\n", (unsigned long long)sink);
    return 0;
}
