#include <X11/Xlib.h>
#include <X11/extensions/XShm.h>

#include <sys/ipc.h>
#include <sys/shm.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <csignal>
#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>
#include <stdexcept>
#include <thread>

#include <X11/Xutil.h>

namespace {

constexpr std::uint32_t kFrameMagic = 0xFB000001;

volatile std::sig_atomic_t g_running = 1;

void handleSignal(int) {
    g_running = 0;
}

int parseInt(const char* value, int fallback) {
    if (value == nullptr || *value == '\0') {
        return fallback;
    }

    char* end = nullptr;
    long parsed = std::strtol(value, &end, 10);
    if (end == value || parsed <= 0) {
        return fallback;
    }

    return static_cast<int>(parsed);
}

void writeAll(int fd, const std::uint8_t* data, std::size_t size) {
    std::size_t written = 0;
    while (written < size && g_running) {
        ssize_t ret = ::write(fd, data + written, size - written);
        if (ret > 0) {
            written += static_cast<std::size_t>(ret);
            continue;
        }

        if (ret < 0 && (errno == EINTR || errno == EAGAIN)) {
            continue;
        }

        throw std::runtime_error("failed to write framebuffer stream");
    }
}

void writeFrame(int width, int height, XImage* image) {
    std::uint32_t header[3] = {
        kFrameMagic,
        static_cast<std::uint32_t>(width),
        static_cast<std::uint32_t>(height),
    };

    writeAll(STDOUT_FILENO, reinterpret_cast<const std::uint8_t*>(header), sizeof(header));

    const std::size_t rowBytes = static_cast<std::size_t>(width) * 4;
    const std::size_t sourceStride = static_cast<std::size_t>(image->bytes_per_line);
    const auto* source = reinterpret_cast<const std::uint8_t*>(image->data);

    if (sourceStride == rowBytes) {
        writeAll(STDOUT_FILENO, source, rowBytes * static_cast<std::size_t>(height));
        return;
    }

    for (int y = 0; y < height; ++y) {
        writeAll(STDOUT_FILENO, source + static_cast<std::size_t>(y) * sourceStride, rowBytes);
    }
}

} // namespace

int main(int argc, char** argv) {
    std::signal(SIGINT, handleSignal);
    std::signal(SIGTERM, handleSignal);

    const std::string displayName = argc > 1 ? argv[1] : ":99";
    const int width = argc > 2 ? parseInt(argv[2], 640) : 640;
    const int height = argc > 3 ? parseInt(argv[3], 480) : 480;
    const int fps = argc > 4 ? parseInt(argv[4], 12) : 12;

    Display* display = XOpenDisplay(displayName.c_str());
    if (display == nullptr) {
        std::cerr << "[XSHM] Failed to open display: " << displayName << '\n';
        return 1;
    }

    if (!XShmQueryExtension(display)) {
        std::cerr << "[XSHM] MIT-SHM extension not available" << '\n';
        XCloseDisplay(display);
        return 1;
    }

    const int screen = DefaultScreen(display);
    const Window root = RootWindow(display, screen);
    Visual* visual = DefaultVisual(display, screen);
    const int depth = DefaultDepth(display, screen);

    XShmSegmentInfo shminfo{};
    XImage* image = XShmCreateImage(
        display,
        visual,
        static_cast<unsigned int>(depth),
        ZPixmap,
        nullptr,
        &shminfo,
        static_cast<unsigned int>(width),
        static_cast<unsigned int>(height));

    if (image == nullptr) {
        std::cerr << "[XSHM] XShmCreateImage failed" << '\n';
        XCloseDisplay(display);
        return 1;
    }

    const std::size_t imageSize = static_cast<std::size_t>(image->bytes_per_line) * static_cast<std::size_t>(image->height);
    shminfo.shmid = shmget(IPC_PRIVATE, imageSize, IPC_CREAT | 0600);
    if (shminfo.shmid < 0) {
        std::cerr << "[XSHM] shmget failed" << '\n';
        XDestroyImage(image);
        XCloseDisplay(display);
        return 1;
    }

    shminfo.shmaddr = static_cast<char*>(shmat(shminfo.shmid, nullptr, 0));
    if (shminfo.shmaddr == reinterpret_cast<char*>(-1)) {
        std::cerr << "[XSHM] shmat failed" << '\n';
        shmctl(shminfo.shmid, IPC_RMID, nullptr);
        XDestroyImage(image);
        XCloseDisplay(display);
        return 1;
    }

    image->data = shminfo.shmaddr;
    shminfo.readOnly = False;

    if (!XShmAttach(display, &shminfo)) {
        std::cerr << "[XSHM] XShmAttach failed" << '\n';
        shmdt(shminfo.shmaddr);
        shmctl(shminfo.shmid, IPC_RMID, nullptr);
        XDestroyImage(image);
        XCloseDisplay(display);
        return 1;
    }

    XSync(display, False);

    const auto frameInterval = std::chrono::milliseconds(std::max(1, 1000 / fps));
    auto nextFrame = std::chrono::steady_clock::now();

    while (g_running) {
        nextFrame += frameInterval;

        if (!XShmGetImage(display, root, image, 0, 0, AllPlanes)) {
            std::this_thread::sleep_for(std::chrono::milliseconds(1));
            continue;
        }

        try {
            writeFrame(width, height, image);
        } catch (const std::exception& exc) {
            std::cerr << "[XSHM] " << exc.what() << '\n';
            break;
        }

        std::this_thread::sleep_until(nextFrame);
    }

    XShmDetach(display, &shminfo);
    XSync(display, False);
    image->data = nullptr;
    XDestroyImage(image);
    shmdt(shminfo.shmaddr);
    shmctl(shminfo.shmid, IPC_RMID, nullptr);
    XCloseDisplay(display);
    return 0;
}