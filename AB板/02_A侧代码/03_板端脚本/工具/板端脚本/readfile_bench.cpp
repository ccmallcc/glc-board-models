// 只为拆解 rans_port 的耗时构成：读 + 解析同一份向量文件要多久？
#include <chrono>
#include <cstdio>
#include <fstream>
#include <sstream>
#include <string>

int main(int argc, char **argv) {
    if (argc < 2) { std::fprintf(stderr, "usage: %s <file>\n", argv[0]); return 2; }
    using C = std::chrono::steady_clock;
    auto ms = [](C::time_point a, C::time_point b) {
        return std::chrono::duration<double, std::milli>(b - a).count();
    };

    // ① 纯字节读
    auto t0 = C::now();
    std::ifstream f(argv[1], std::ios::binary);
    std::string all((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    auto t1 = C::now();

    // ② 按行解析成整数（模拟 rans_port 的解析开销）
    auto t2 = C::now();
    std::istringstream is(all);
    std::string line;
    long lines = 0, toks = 0;
    long long acc = 0;
    while (std::getline(is, line)) {
        ++lines;
        std::istringstream ls(line);
        long long v;
        while (ls >> v) { ++toks; acc += v; }
    }
    auto t3 = C::now();

    std::printf("file      : %s\n", argv[1]);
    std::printf("bytes     : %zu\n", all.size());
    std::printf("read      : %8.2f ms\n", ms(t0, t1));
    std::printf("parse     : %8.2f ms   (lines=%ld toks=%ld sum=%lld)\n",
                ms(t2, t3), lines, toks, acc);
    std::printf("read+parse: %8.2f ms\n", ms(t0, t3));
    return 0;
}
