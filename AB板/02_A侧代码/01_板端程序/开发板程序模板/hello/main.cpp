// 最小示例：证明交叉编译链路通。
// 故意用了 <thread> / <chrono>：这两个头在交叉编译里最容易暴露 sysroot 问题。
#include <cstdint>
#include <cstdio>
#include <thread>
#include <chrono>

int main() {
    std::printf("=== hello from the board ===\n");
    std::printf("  sizeof(void*)        = %zu\n", sizeof(void*));
    std::printf("  sizeof(long)         = %zu\n", sizeof(long));
    std::printf("  hardware_concurrency = %u\n", std::thread::hardware_concurrency());
    std::printf("  __aarch64__          = %d\n",
#if defined(__aarch64__)
                1
#else
                0
#endif
    );

    // 一句话计时演示：steady_clock 在 aarch64 上走的是 ARM 通用计时器
    auto t0 = std::chrono::steady_clock::now();
    volatile std::uint64_t acc = 0;
    for (std::uint64_t i = 0; i < 10000000ULL; ++i) acc += i;   // 别让编译器把这个循环删掉
    auto t1 = std::chrono::steady_clock::now();
    double ns = std::chrono::duration<double, std::nano>(t1 - t0).count();
    std::printf("  1e7 次累加            = %.1f ms  (%.2f ns/次)\n", ns / 1e6, ns / 1e7);

    return 0;
}
