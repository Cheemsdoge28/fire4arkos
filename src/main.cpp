#include <SDL2/SDL.h>

#include <algorithm>
#include <array>
#include <cctype>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <optional>
#include <string>
#include <vector>
#include <cstring>
#include <chrono>
#include <thread>

#include <fstream>
#include <mutex>
#include <iomanip>

#ifdef _WIN32
#include <windows.h>
#include <libloaderapi.h>
#else
#include <unistd.h>
#include <sys/wait.h>
#include <signal.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#endif

namespace {

struct LaunchOptions {
    std::string initialUrl{"https://www.google.com"};
    std::filesystem::path executablePath;
};

// Simple thread-safe logger that writes to a file and stderr.
static std::ofstream g_logFile;
static std::mutex g_logMutex;

static std::string nowString() {
    using namespace std::chrono;
    auto now = system_clock::now();
    auto tt = system_clock::to_time_t(now);
    std::tm tm{};
#ifdef _WIN32
    localtime_s(&tm, &tt);
#else
    localtime_r(&tt, &tm);
#endif
    std::ostringstream ss;
    ss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
    return ss.str();
}

static void initLogging() {
    const char* env = std::getenv("FIRE4ARKOS_LOG");
    std::string path = env ? env : "/tmp/fire4arkos.log";
    // On Windows, default to current folder if /tmp likely doesn't exist
#ifdef _WIN32
    if (path.rfind("/tmp/", 0) == 0) path = std::string(".") + "/fire4arkos.log";
#endif
    std::lock_guard<std::mutex> lk(g_logMutex);
    g_logFile.open(path, std::ios::app);
    if (g_logFile) {
        g_logFile << "[I] " << nowString() << " - Logger started\n";
    }
}

static void logMessage(const char* level, const std::string& msg) {
    std::lock_guard<std::mutex> lk(g_logMutex);
    std::string line = std::string("[") + level + "] " + nowString() + " - " + msg;
    if (g_logFile) g_logFile << line << '\n';
    // also mirror to stderr for real-time visibility
    std::cerr << line << std::endl;
}

static void logInfo(const std::string& msg) { logMessage("I", msg); }
static void logWarn(const std::string& msg) { logMessage("W", msg); }
static void logError(const std::string& msg) { logMessage("E", msg); }

static std::filesystem::path executableDirectory(const std::filesystem::path& argv0) {
#ifdef _WIN32
    std::vector<char> buffer(MAX_PATH);
    DWORD len = GetModuleFileNameA(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (len > 0 && len < buffer.size()) {
        return std::filesystem::path(std::string(buffer.data(), len)).parent_path();
    }
#endif

    std::error_code ec;
    auto resolved = std::filesystem::weakly_canonical(argv0, ec);
    if (!ec && resolved.has_parent_path()) {
        return resolved.parent_path();
    }

    if (argv0.has_parent_path()) {
        return std::filesystem::absolute(argv0, ec).parent_path();
    }

    return std::filesystem::current_path(ec);
}

static std::string percentEncode(const std::string& input) {
    static constexpr char hex[] = "0123456789ABCDEF";
    std::string encoded;
    encoded.reserve(input.size() * 3);

    for (unsigned char ch : input) {
        if (std::isalnum(ch) || ch == '-' || ch == '_' || ch == '.' || ch == '~') {
            encoded.push_back(static_cast<char>(ch));
            continue;
        }

        encoded.push_back('%');
        encoded.push_back(hex[(ch >> 4) & 0x0F]);
        encoded.push_back(hex[ch & 0x0F]);
    }

    return encoded;
}


// Simple cross-platform IPC pipe for command communication
class CommandPipe {
public:
    bool create(const std::string& baseName) {
#ifdef _WIN32
        // Create named pipes on Windows for commands
        pipeIn_ = CreateNamedPipeA(
            ("\\\\.\\pipe\\" + baseName + "_in").c_str(),
            PIPE_ACCESS_OUTBOUND,
            PIPE_TYPE_BYTE,  // Changed to BYTE mode for streaming
            1, 65536, 65536, 0, nullptr);
        
        pipeOut_ = CreateNamedPipeA(
            ("\\\\.\\pipe\\" + baseName + "_out").c_str(),
            PIPE_ACCESS_INBOUND,
            PIPE_TYPE_BYTE,  // Changed to BYTE mode for streaming
            1, 65536, 65536, 0, nullptr);
        
        // Create framebuffer streaming pipe (output only)
        fbPipe_ = CreateNamedPipeA(
            ("\\\\.\\pipe\\" + baseName + "_fb").c_str(),
            PIPE_ACCESS_INBOUND,
            PIPE_TYPE_BYTE,
            1, 1048576, 1048576, 0, nullptr);
        
        return pipeIn_ != INVALID_HANDLE_VALUE && pipeOut_ != INVALID_HANDLE_VALUE && fbPipe_ != INVALID_HANDLE_VALUE;
#else
        // Use FIFOs on Unix
        std::string pipeInPath = "/tmp/" + baseName + "_in";
        std::string pipeOutPath = "/tmp/" + baseName + "_out";
        std::string fbPath = "/tmp/" + baseName + "_fb";
        
        mkfifo(pipeInPath.c_str(), 0666);
        mkfifo(pipeOutPath.c_str(), 0666);
        mkfifo(fbPath.c_str(), 0666);
        
        pipeInPath_ = pipeInPath;
        pipeOutPath_ = pipeOutPath;
        fbPath_ = fbPath;
        return true;
#endif
    }

    bool sendCommand(const std::string& cmd) {
#ifdef _WIN32
        if (pipeIn_ == INVALID_HANDLE_VALUE) return false;
        
        DWORD written = 0;
        return WriteFile(pipeIn_, cmd.c_str(), (DWORD)cmd.size(), &written, nullptr) && written > 0;
#else
        if (pipeInFd_ < 0) {
            pipeInFd_ = open(pipeInPath_.c_str(), O_WRONLY | O_NONBLOCK);
            if (pipeInFd_ < 0) return false;
        }
        
        ssize_t ret = write(pipeInFd_, cmd.c_str(), cmd.size());
        return ret > 0;
#endif
    }

    ~CommandPipe() {
#ifdef _WIN32
        if (pipeIn_ != INVALID_HANDLE_VALUE) CloseHandle(pipeIn_);
        if (pipeOut_ != INVALID_HANDLE_VALUE) CloseHandle(pipeOut_);
        if (fbPipe_ != INVALID_HANDLE_VALUE) CloseHandle(fbPipe_);
#else
        if (pipeInFd_ >= 0) close(pipeInFd_);
        if (pipeOutFd_ >= 0) close(pipeOutFd_);
        unlink(pipeInPath_.c_str());
        unlink(pipeOutPath_.c_str());
        unlink(fbPath_.c_str());
#endif
    }

private:
#ifdef _WIN32
    HANDLE pipeIn_{INVALID_HANDLE_VALUE};
    HANDLE pipeOut_{INVALID_HANDLE_VALUE};
    HANDLE fbPipe_{INVALID_HANDLE_VALUE};
#else
    int pipeInFd_{-1};
    int pipeOutFd_{-1};
    std::string pipeInPath_;
    std::string pipeOutPath_;
    std::string fbPath_;
#endif
    friend class FramebufferReader;
};

// Framebuffer holder for captured screenshots with delta tracking
struct Framebuffer {
    std::vector<uint8_t> data;
    int width = 0;
    int height = 0;
    uint64_t timestamp = 0;
    bool dirty = false;
    
    // Delta encoding: only redraw changed regions
    struct DirtyRect {
        int x, y, w, h;
    } dirtyRect{0, 0, 0, 0};
    
    // Frame rate limiting: target 30 FPS (~33ms per frame)
    using ClockType = std::chrono::steady_clock;
    static constexpr std::chrono::milliseconds targetFrameTime{33};
    ClockType::time_point lastFrameTime{ClockType::now()};
    
    bool shouldUpdate() {
        auto now = ClockType::now();
        if (now - lastFrameTime >= targetFrameTime) {
            lastFrameTime = now;
            return true;
        }
        return false;
    }
    
    void resize(int w, int h) {
        if (w != width || h != height) {
            width = w;
            height = h;
            data.clear();
            data.resize(w * h * 4, 0);  // RGBA8888
            dirtyRect = {0, 0, w, h};
            dirty = true;
        }
    }
};

// High-performance framebuffer reader with streaming support
class FramebufferReader {
public:
    bool initialize(const std::string& baseName) {
        std::string fbPath = "/tmp/" + baseName + "_fb";
        
#ifdef _WIN32
        // Open named pipe for reading framebuffer stream
        fbPipe_ = CreateFileA(
            ("\\\\.\\pipe\\" + baseName + "_fb").c_str(),
            GENERIC_READ,
            0,
            nullptr,
            OPEN_EXISTING,
            FILE_FLAG_OVERLAPPED,  // Non-blocking I/O
            nullptr);
        
        return fbPipe_ != INVALID_HANDLE_VALUE;
#else
        // Open FIFO for reading framebuffer stream (non-blocking)
        mkfifo(fbPath.c_str(), 0666);
        fbFd_ = open(fbPath.c_str(), O_RDONLY | O_NONBLOCK);
        fbPath_ = fbPath;
        return fbFd_ >= 0;
#endif
    }
    
    // Attempt to read available frame data (non-blocking)
    bool tryReadFrame(Framebuffer& fb) {
#ifdef _WIN32
        if (fbPipe_ == INVALID_HANDLE_VALUE) return false;
        
        uint8_t header[12];  // Magic (4) + Width (4) + Height (4)
        DWORD bytesRead = 0;
        
        // Try to read frame header
        if (!ReadFile(fbPipe_, header, 12, &bytesRead, nullptr)) {
            // No data available yet
            return false;
        }
        
        if (bytesRead < 12) return false;
        
        // Validate magic number
        uint32_t magic = *(uint32_t*)header;
        if (magic != 0xFB000001) {
            std::cerr << "[FB] Invalid magic: 0x" << std::hex << magic << std::dec << "\n";
            {
                std::ostringstream ss; ss << "[FB] Invalid magic: 0x" << std::hex << magic << std::dec;
                logError(ss.str());
            }
            return false;
        }
        
        uint32_t width = *(uint32_t*)(header + 4);
        uint32_t height = *(uint32_t*)(header + 8);
        
        if (width == 0 || height == 0 || width > 2560 || height > 1440) {
            std::cerr << "[FB] Invalid dimensions: " << width << "x" << height << "\n";
            {
                std::ostringstream ss; ss << "[FB] Invalid dimensions: " << width << "x" << height;
                logError(ss.str());
            }
            return false;
        }
        
        // Resize framebuffer if needed
        if (fb.width != (int)width || fb.height != (int)height) {
            fb.resize((int)width, (int)height);
        }
        
        // Read pixel data
        size_t pixelBytes = width * height * 4;
        if (!ReadFile(fbPipe_, fb.data.data(), (DWORD)pixelBytes, &bytesRead, nullptr)) {
            return false;
        }
        
        if (bytesRead == pixelBytes) {
            fb.dirty = true;
            fb.timestamp = std::time(nullptr);
            return true;
        }
        
        return false;
#else
        if (fbFd_ < 0) return false;
        
        uint8_t header[12];
        ssize_t ret = read(fbFd_, header, 12);
        
        if (ret < 12) return false;  // Header incomplete
        
        // Validate magic
        uint32_t magic = *(uint32_t*)header;
        if (magic != 0xFB000001) {
            std::cerr << "[FB] Invalid magic: 0x" << std::hex << magic << std::dec << "\n";
            {
                std::ostringstream ss; ss << "[FB] Invalid magic: 0x" << std::hex << magic << std::dec;
                logError(ss.str());
            }
            return false;
        }
        
        uint32_t width = *(uint32_t*)(header + 4);
        uint32_t height = *(uint32_t*)(header + 8);
        
        if (width == 0 || height == 0 || width > 2560 || height > 1440) {
            std::cerr << "[FB] Invalid dimensions: " << width << "x" << height << "\n";
            {
                std::ostringstream ss; ss << "[FB] Invalid dimensions: " << width << "x" << height;
                logError(ss.str());
            }
            return false;
        }
        
        if (fb.width != (int)width || fb.height != (int)height) {
            fb.resize((int)width, (int)height);
        }
        
        size_t pixelBytes = width * height * 4;
        ret = read(fbFd_, fb.data.data(), pixelBytes);
        
        if (ret == (ssize_t)pixelBytes) {
            fb.dirty = true;
            fb.timestamp = std::time(nullptr);
            return true;
        }
        
        return false;
#endif
    }
    
    ~FramebufferReader() {
#ifdef _WIN32
        if (fbPipe_ != INVALID_HANDLE_VALUE) {
            CloseHandle(fbPipe_);
            fbPipe_ = INVALID_HANDLE_VALUE;
        }
#else
        if (fbFd_ >= 0) {
            close(fbFd_);
            fbFd_ = -1;
        }
        if (!fbPath_.empty()) {
            unlink(fbPath_.c_str());
        }
#endif
    }

private:
#ifdef _WIN32
    HANDLE fbPipe_{INVALID_HANDLE_VALUE};
#else
    int fbFd_{-1};
    std::string fbPath_;
#endif
};

struct BrowserState {
    enum class InputMode {
        None,
        Url,
        PageText
    };

    std::string currentUrl{"https://www.google.com"};
    std::vector<std::string> history;
    std::vector<std::string> forwardStack;
    std::string urlBuffer{currentUrl};
    std::string textBuffer;
    int scrollOffset{0};
    bool requestReload{false};
    bool running{true};
    InputMode inputMode{InputMode::None};
    int keyboardRow{0};
    int keyboardCol{0};
    bool showUi{true};
};

class BrowserBackend {
public:
    virtual ~BrowserBackend() = default;
    virtual bool initialize(SDL_Window* window, const std::string& initialUrl) = 0;
    virtual bool loadUrl(const std::string& url) = 0;
    virtual void goBack() = 0;
    virtual void scrollBy(int deltaLines) = 0;
    virtual void clickFocusedElement() = 0;
    virtual void resize(int width, int height) = 0;
    virtual void typeText(const std::string& text) = 0;
    virtual void pressKey(const std::string& key) = 0;
    virtual void pump() = 0;
    virtual bool captureFrame(Framebuffer& fb) = 0;
};

class FirefoxProcessBackend final : public BrowserBackend {
public:
    explicit FirefoxProcessBackend(std::filesystem::path executableDir)
        : executableDir_(std::move(executableDir)) {}

    ~FirefoxProcessBackend() {
        shutdown();
    }

    bool initialize(SDL_Window* window, const std::string& initialUrl) override {
        window_ = window;
        currentUrl_ = initialUrl;
        return launchFirefox(initialUrl);
    }

    bool loadUrl(const std::string& url) override {
        currentUrl_ = url;
        return sendCommand("load:" + url);
    }

    void goBack() override {
        sendCommand("back");
    }

    void scrollBy(int deltaLines) override {
        sendCommand("scroll:" + std::to_string(deltaLines));
    }

    void clickFocusedElement() override {
        sendCommand("click");
    }

    void resize(int width, int height) override {
        width_ = width;
        height_ = height;
        sendCommand("resize:" + std::to_string(width) + "," + std::to_string(height));
    }

    void typeText(const std::string& text) override {
        sendCommand("text:" + percentEncode(text));
    }

    void pressKey(const std::string& key) override {
        sendCommand("key:" + key);
    }

    void pump() override {
        if (window_ != nullptr) {
            std::string title = "Firefox Headless | " + currentUrl_;
            SDL_SetWindowTitle(window_, title.c_str());
        }
    }

    // Capture a screenshot from Firefox process (non-blocking streaming)
    bool captureFrame(Framebuffer& fb) {
        if (!isRunning_) {
            return false;
        }

        // Only attempt to read if enough time has passed (frame rate limiting)
        if (!fb.shouldUpdate()) {
            return false;
        }

        // Try to read available frame from streaming pipe (non-blocking)
        return fbReader_.tryReadFrame(fb);
    }

private:
    std::optional<std::string> findWrapperPath() const {
        if (const char* env = std::getenv("FIRE4ARKOS_WRAPPER"); env != nullptr && *env != '\0') {
            return std::string(env);
        }

        std::vector<std::filesystem::path> candidates = {
            executableDir_ / "firefox-framebuffer-wrapper.py",
            executableDir_.parent_path() / "firefox-framebuffer-wrapper.py",
            std::filesystem::current_path() / "firefox-framebuffer-wrapper.py",
            "/usr/local/bin/firefox-framebuffer-wrapper.py",
            "/opt/fire4arkos/firefox-framebuffer-wrapper.py"
        };

        for (const auto& candidate : candidates) {
            if (!candidate.empty() && std::filesystem::exists(candidate)) {
                return candidate.string();
            }
        }

        return std::nullopt;
    }

    bool launchFirefox(const std::string& url) {
        auto wrapperPath = findWrapperPath();
        if (!wrapperPath) {
            logError("Could not locate firefox-framebuffer-wrapper.py");
            return false;
        }

        // Create IPC pipes for command communication
        if (!cmdPipe_.create("fire4arkos")) {
            std::cerr << "Failed to create command pipes\n";
            logError("Failed to create command pipes");
            return false;
        }

        // Initialize framebuffer reader for streaming frames
        if (!fbReader_.initialize("fire4arkos")) {
            std::cerr << "Warning: Failed to initialize framebuffer reader\n";
            logWarn("Failed to initialize framebuffer reader");
            // Don't fail here - renderer might work without streaming
        }
        
#ifdef _WIN32
        std::string cmdline = "py -3 \"" + *wrapperPath + "\" \"" + url + "\" fire4arkos";
        STARTUPINFOA si = {};
        PROCESS_INFORMATION pi = {};
        si.cb = sizeof(si);

        if (!CreateProcessA(nullptr, (LPSTR)cmdline.c_str(), nullptr, nullptr, FALSE, 
                           CREATE_NO_WINDOW, nullptr, nullptr, &si, &pi)) {
            std::string err = "Failed to launch wrapper: " + std::to_string(GetLastError());
            std::cerr << err << '\n';
            std::cerr << "Cmdline: " << cmdline << '\n';
            logError(err + " Cmdline: " + cmdline);
            return false;
        }

        processHandle_ = pi.hProcess;
        CloseHandle(pi.hThread);
        {
            std::ostringstream ss; ss << "Launched wrapper process: " << pi.dwProcessId;
            std::cout << ss.str() << '\n';
            logInfo(ss.str());
        }
#else
        // Unix-like systems
        pid_t pid = fork();
        if (pid == -1) {
            std::cerr << "fork() failed\n";
            logError("fork() failed");
            return false;
        }

        if (pid == 0) {
            // Child process - execute Python wrapper
            execlp("python3", "python3", wrapperPath->c_str(), url.c_str(), "fire4arkos", nullptr);
            
            // If Python not available, try with python
            execlp("python", "python", wrapperPath->c_str(), url.c_str(), "fire4arkos", nullptr);
            
            std::cerr << "execlp failed: Python not found\n";
            logError("execlp failed: Python not found");
            exit(1);
        }

        processId_ = pid;
        {
            std::ostringstream ss; ss << "Launched wrapper process: " << pid;
            std::cout << ss.str() << '\n';
            logInfo(ss.str());
        }
#endif

        // Wait a bit for pipes to be created
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
        
        isRunning_ = true;
        return true;
    }

    bool sendCommand(const std::string& cmd) {
        if (!isRunning_) {
            return false;
        }

        // Send command via IPC pipe
        std::cout << "[IPC] " << cmd;
        logInfo(std::string("IPC => ") + cmd);
        return cmdPipe_.sendCommand(cmd + "\n");
    }

    void shutdown() {
        if (!isRunning_) {
            return;
        }

#ifdef _WIN32
        if (processHandle_ != nullptr) {
            TerminateProcess(processHandle_, 0);
            WaitForSingleObject(processHandle_, INFINITE);
            CloseHandle(processHandle_);
            processHandle_ = nullptr;
        }
#else
        if (processId_ > 0) {
            kill(processId_, SIGTERM);
            int status = 0;
            waitpid(processId_, &status, 0);
            processId_ = 0;
        }
#endif

        isRunning_ = false;
    }

    static std::string findFirefoxExecutable() {
        // Try common Firefox paths
        std::vector<std::string> candidates = {
#ifdef _WIN32
            "C:\\Program Files\\Mozilla Firefox\\firefox.exe",
            "C:\\Program Files (x86)\\Mozilla Firefox\\firefox.exe",
            "firefox.exe"
#else
            "/usr/bin/firefox",
            "/usr/local/bin/firefox",
            "firefox"
#endif
        };

        for (const auto& path : candidates) {
            if (std::filesystem::exists(path)) {
                return path;
            }
        }

        // Fall back to PATH search
        return "firefox";
    }

    SDL_Window* window_{nullptr};
    std::string currentUrl_;
    std::filesystem::path executableDir_;
    int width_{640};
    int height_{480};
    bool isRunning_{false};
    CommandPipe cmdPipe_;
    FramebufferReader fbReader_;

#ifdef _WIN32
    HANDLE processHandle_{nullptr};
#else
    pid_t processId_{0};
#endif
};

class App final {
public:
    explicit App(LaunchOptions options)
        : backend_(executableDirectory(options.executablePath)) {
        state_.currentUrl = options.initialUrl;
        state_.urlBuffer = options.initialUrl;
    }

    bool initialize() {
        if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_EVENTS | SDL_INIT_JOYSTICK | SDL_INIT_GAMECONTROLLER) != 0) {
            std::string err = std::string("SDL_Init failed: ") + SDL_GetError();
            std::cerr << err << '\n';
            logError(err);
            return false;
        }

        SDL_GameControllerEventState(SDL_ENABLE);

        if (!createWindow()) {
            return false;
        }

        openController();

        if (!backend_.initialize(window_, state_.currentUrl)) {
            std::cerr << "Backend initialization failed\n";
            logError("Backend initialization failed");
            return false;
        }

        SDL_StartTextInput();
        updateTitle();
        return true;
    }

    void run() {
        SDL_Event event{};
        while (state_.running) {
            while (SDL_PollEvent(&event) != 0) {
                handleEvent(event);
            }

            if (state_.requestReload) {
                state_.requestReload = false;
                backend_.loadUrl(state_.currentUrl);
            }

            backend_.pump();
            // Capture frames from Firefox backend
            backend_.captureFrame(framebuffer_);
            renderFrame();
            SDL_Delay(16);
        }
    }

    void shutdown() {
        SDL_StopTextInput();
        closeController();
        if (framebufferTexture_ != nullptr) {
            SDL_DestroyTexture(framebufferTexture_);
            framebufferTexture_ = nullptr;
        }
        if (renderer_ != nullptr) {
            SDL_DestroyRenderer(renderer_);
        }
        if (window_ != nullptr) {
            SDL_DestroyWindow(window_);
        }
        SDL_Quit();
    }

private:
    bool createWindow() {
        window_ = SDL_CreateWindow(
            "R36S Browser",
            SDL_WINDOWPOS_CENTERED,
            SDL_WINDOWPOS_CENTERED,
            640,
            480,
            SDL_WINDOW_SHOWN | SDL_WINDOW_RESIZABLE);

        if (window_ == nullptr) {
            std::string err = std::string("SDL_CreateWindow failed: ") + SDL_GetError();
            std::cerr << err << '\n';
            logError(err);
            return false;
        }

        renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
        if (renderer_ == nullptr) {
            renderer_ = SDL_CreateRenderer(window_, -1, SDL_RENDERER_SOFTWARE);
        }

        if (renderer_ == nullptr) {
            std::string err = std::string("SDL_CreateRenderer failed: ") + SDL_GetError();
            std::cerr << err << '\n';
            logError(err);
            return false;
        }

        int width = 0;
        int height = 0;
        SDL_GetWindowSize(window_, &width, &height);
        backend_.resize(width, height);
        return true;
    }

    void handleEvent(const SDL_Event& event) {
        switch (event.type) {
        case SDL_QUIT:
            state_.running = false;
            break;
        case SDL_CONTROLLERDEVICEADDED:
            openController();
            break;
        case SDL_CONTROLLERDEVICEREMOVED:
            closeController();
            openController();
            break;
        case SDL_CONTROLLERBUTTONDOWN:
            handleControllerButton(static_cast<SDL_GameControllerButton>(event.cbutton.button));
            break;
        case SDL_JOYHATMOTION:
            handleJoyHat(event.jhat.value);
            break;
        case SDL_JOYBUTTONDOWN:
            handleJoyButton(event.jbutton.button);
            break;
        case SDL_WINDOWEVENT:
            if (event.window.event == SDL_WINDOWEVENT_SIZE_CHANGED) {
                backend_.resize(event.window.data1, event.window.data2);
            }
            break;
        case SDL_TEXTINPUT:
            handleTextInput(event.text.text);
            break;
        case SDL_KEYDOWN:
            handleKey(event.key.keysym.sym);
            break;
        default:
            break;
        }
    }

    void handleKey(SDL_Keycode key) {
        if (hasActiveKeyboard()) {
            handleKeyboardOverlayKey(key);
            return;
        }

        switch (key) {
        case SDLK_UP:
            backend_.scrollBy(-5);
            state_.scrollOffset -= 5;
            break;
        case SDLK_DOWN:
            backend_.scrollBy(5);
            state_.scrollOffset += 5;
            break;
        case SDLK_LEFT:
            backend_.scrollBy(-1);
            break;
        case SDLK_RIGHT:
            backend_.scrollBy(1);
            break;
        case SDLK_RETURN:
            backend_.clickFocusedElement();
            break;
        case SDLK_TAB:
        case SDLK_s:
            openKeyboard(BrowserState::InputMode::Url);
            break;
        case SDLK_t:
            openKeyboard(BrowserState::InputMode::PageText);
            break;
        case SDLK_BACKSPACE:
            navigateBack();
            break;
        case SDLK_r:
            state_.requestReload = true;
            break;
        case SDLK_q:
        case SDLK_ESCAPE:
            state_.running = false;
            break;
        default:
            break;
        }
    }

    void handleKeyboardOverlayKey(SDL_Keycode key) {
        switch (key) {
        case SDLK_UP:
            moveKeyboardSelection(-1, 0);
            break;
        case SDLK_DOWN:
            moveKeyboardSelection(1, 0);
            break;
        case SDLK_LEFT:
            moveKeyboardSelection(0, -1);
            break;
        case SDLK_RIGHT:
            moveKeyboardSelection(0, 1);
            break;
        case SDLK_RETURN:
            activateSelectedKey();
            break;
        case SDLK_ESCAPE:
            closeKeyboard(false);
            break;
        case SDLK_BACKSPACE:
            eraseActiveBufferChar();
            updateTitle();
            break;
        case SDLK_TAB:
            if (state_.inputMode == BrowserState::InputMode::PageText) {
                applyBufferedPageText();
                backend_.pressKey("Tab");
            }
            break;
        default:
            break;
        }
    }

    void handleControllerButton(SDL_GameControllerButton button) {
        if (button == SDL_CONTROLLER_BUTTON_A) {
            if (hasActiveKeyboard()) {
                activateSelectedKey();
            } else {
                backend_.clickFocusedElement();
            }
            return;
        }

        if (button == SDL_CONTROLLER_BUTTON_B) {
            if (hasActiveKeyboard()) {
                closeKeyboard(false);
            } else {
                navigateBack();
            }
            return;
        }

        if (button == SDL_CONTROLLER_BUTTON_X) {
            if (hasActiveKeyboard()) {
                eraseActiveBufferChar();
                updateTitle();
            } else {
                state_.requestReload = true;
            }
            return;
        }

        if (button == SDL_CONTROLLER_BUTTON_Y) {
            openKeyboard(BrowserState::InputMode::Url);
            return;
        }

        if (button == SDL_CONTROLLER_BUTTON_LEFTSHOULDER) {
            openKeyboard(BrowserState::InputMode::PageText);
        } else if (button == SDL_CONTROLLER_BUTTON_DPAD_UP) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(-1, 0);
                return;
            }
            backend_.scrollBy(-5);
            state_.scrollOffset -= 5;
        } else if (button == SDL_CONTROLLER_BUTTON_DPAD_DOWN) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(1, 0);
                return;
            }
            backend_.scrollBy(5);
            state_.scrollOffset += 5;
        } else if (button == SDL_CONTROLLER_BUTTON_DPAD_LEFT) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(0, -1);
                return;
            }
            backend_.scrollBy(-1);
        } else if (button == SDL_CONTROLLER_BUTTON_DPAD_RIGHT) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(0, 1);
                return;
            }
            backend_.scrollBy(1);
        } else if (button == SDL_CONTROLLER_BUTTON_RIGHTSHOULDER) {
            state_.showUi = !state_.showUi;
        }
    }

    void handleJoyHat(Uint8 value) {
        if (value & SDL_HAT_UP) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(-1, 0);
                return;
            }
            backend_.scrollBy(-5);
            state_.scrollOffset -= 5;
        }
        if (value & SDL_HAT_DOWN) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(1, 0);
                return;
            }
            backend_.scrollBy(5);
            state_.scrollOffset += 5;
        }
        if (value & SDL_HAT_LEFT) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(0, -1);
                return;
            }
            backend_.scrollBy(-1);
        }
        if (value & SDL_HAT_RIGHT) {
            if (hasActiveKeyboard()) {
                moveKeyboardSelection(0, 1);
                return;
            }
            backend_.scrollBy(1);
        }
    }

    void handleJoyButton(Uint8 button) {
        switch (button) {
        case 0: // B (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_B);
            break;
        case 1: // A (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_A);
            break;
        case 2: // X (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_X);
            break;
        case 3: // Y (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_Y);
            break;
        case 4: // L1 (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_LEFTSHOULDER);
            break;
        case 5: // R1 (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_RIGHTSHOULDER);
            break;
        case 8: // D-Pad Up (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_DPAD_UP);
            break;
        case 9: // D-Pad Down (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_DPAD_DOWN);
            break;
        case 10: // D-Pad Left (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_DPAD_LEFT);
            break;
        case 11: // D-Pad Right (R36S)
            handleControllerButton(SDL_CONTROLLER_BUTTON_DPAD_RIGHT);
            break;
        case 13: // Start (R36S) - Add shortcut to exit
            state_.running = false;
            break;
        default:
            break;
        }
    }

    bool hasActiveKeyboard() const {
        return state_.inputMode != BrowserState::InputMode::None;
    }

    std::string& activeBuffer() {
        return state_.inputMode == BrowserState::InputMode::Url ? state_.urlBuffer : state_.textBuffer;
    }

    const std::string& activeBuffer() const {
        return state_.inputMode == BrowserState::InputMode::Url ? state_.urlBuffer : state_.textBuffer;
    }

    void openKeyboard(BrowserState::InputMode mode) {
        state_.inputMode = mode;
        if (mode == BrowserState::InputMode::Url) {
            state_.urlBuffer = state_.currentUrl;
        } else if (mode == BrowserState::InputMode::PageText) {
            state_.textBuffer.clear();
        }
        state_.keyboardRow = 0;
        state_.keyboardCol = 0;
        updateTitle();
    }

    void closeKeyboard(bool keepBuffer) {
        if (!keepBuffer) {
            if (state_.inputMode == BrowserState::InputMode::Url) {
                state_.urlBuffer = state_.currentUrl;
            } else if (state_.inputMode == BrowserState::InputMode::PageText) {
                state_.textBuffer.clear();
            }
        }
        state_.inputMode = BrowserState::InputMode::None;
        updateTitle();
    }

    void navigateBack() {
        backend_.goBack();
        if (state_.history.size() > 1) {
            state_.forwardStack.push_back(state_.currentUrl);
            state_.currentUrl = state_.history[state_.history.size() - 2];
            state_.history.pop_back();
            state_.urlBuffer = state_.currentUrl;
            state_.requestReload = true;
        }
    }

    void handleTextInput(const char* text) {
        if (!hasActiveKeyboard()) {
            return;
        }
        activeBuffer() += text;
        updateTitle();
    }

    void eraseActiveBufferChar() {
        auto& buffer = activeBuffer();
        if (!buffer.empty()) {
            buffer.pop_back();
        }
    }

    struct KeyboardKey {
        const char* label;
        const char* value;
    };

    static const std::vector<std::vector<KeyboardKey>>& keyboardLayout() {
        static const std::vector<std::vector<KeyboardKey>> layout = {
            {{"1", "1"}, {"2", "2"}, {"3", "3"}, {"4", "4"}, {"5", "5"}, {"6", "6"},
             {"7", "7"}, {"8", "8"}, {"9", "9"}, {"0", "0"}, {"-", "-"}, {".", "."}},
            {{"q", "q"}, {"w", "w"}, {"e", "e"}, {"r", "r"}, {"t", "t"}, {"y", "y"},
             {"u", "u"}, {"i", "i"}, {"o", "o"}, {"p", "p"}, {"/", "/"}, {":", ":"}},
            {{"a", "a"}, {"s", "s"}, {"d", "d"}, {"f", "f"}, {"g", "g"}, {"h", "h"},
             {"j", "j"}, {"k", "k"}, {"l", "l"}, {"_", "_"}, {"@", "@"}, {"?", "?"}},
            {{"z", "z"}, {"x", "x"}, {"c", "c"}, {"v", "v"}, {"b", "b"}, {"n", "n"},
             {"m", "m"}, {"&", "&"}, {"=", "="}, {"+", "+"}, {"#", "#"}, {"%", "%"}},
            {{"SPACE", " "}, {"BKSP", "__BACKSPACE__"}, {"TAB", "__TAB__"},
             {"ENTER", "__ENTER__"}, {"OK", "__OK__"}, {"CANCEL", "__CANCEL__"}}
        };
        return layout;
    }

    void moveKeyboardSelection(int rowDelta, int colDelta) {
        if (!hasActiveKeyboard()) {
            return;
        }
        const auto& layout = keyboardLayout();
        state_.keyboardRow = (state_.keyboardRow + rowDelta + static_cast<int>(layout.size())) %
                             static_cast<int>(layout.size());
        const auto& row = layout[static_cast<size_t>(state_.keyboardRow)];
        int width = static_cast<int>(row.size());
        state_.keyboardCol = (state_.keyboardCol + colDelta + width) % width;
    }

    void applyBufferedPageText() {
        if (!state_.textBuffer.empty()) {
            backend_.typeText(state_.textBuffer);
            state_.textBuffer.clear();
        }
        updateTitle();
    }

    void activateSelectedKey() {
        if (!hasActiveKeyboard()) {
            return;
        }

        const auto& key = keyboardLayout()[static_cast<size_t>(state_.keyboardRow)]
                                         [static_cast<size_t>(state_.keyboardCol)];
        const std::string value = key.value;

        if (value == "__BACKSPACE__") {
            eraseActiveBufferChar();
        } else if (value == "__TAB__") {
            if (state_.inputMode == BrowserState::InputMode::PageText) {
                applyBufferedPageText();
                backend_.pressKey("Tab");
            }
        } else if (value == "__ENTER__") {
            if (state_.inputMode == BrowserState::InputMode::Url) {
                commitUrlEdit();
                return;
            }
            applyBufferedPageText();
            backend_.pressKey("Return");
            closeKeyboard(true);
            return;
        } else if (value == "__OK__") {
            if (state_.inputMode == BrowserState::InputMode::Url) {
                commitUrlEdit();
                return;
            }
            applyBufferedPageText();
            closeKeyboard(true);
            return;
        } else if (value == "__CANCEL__") {
            closeKeyboard(false);
            return;
        } else {
            activeBuffer() += value;
        }

        updateTitle();
    }

    void openController() {
        if (controller_ != nullptr) {
            return;
        }

        const int joystickCount = SDL_NumJoysticks();
        for (int index = 0; index < joystickCount; ++index) {
            if (SDL_IsGameController(index)) {
                controller_ = SDL_GameControllerOpen(index);
                if (controller_ != nullptr) {
                    std::ostringstream ss;
                    ss << "Opened SDL game controller: " << SDL_GameControllerName(controller_);
                    logInfo(ss.str());
                    return;
                }
            }
        }

        if (joystickCount > 0) {
            joystick_ = SDL_JoystickOpen(0);
            if (joystick_ != nullptr) {
                std::ostringstream ss;
                ss << "Opened SDL joystick fallback: " << SDL_JoystickName(joystick_);
                logInfo(ss.str());
            }
        }
    }

    void closeController() {
        if (controller_ != nullptr) {
            SDL_GameControllerClose(controller_);
            controller_ = nullptr;
        }
        if (joystick_ != nullptr) {
            SDL_JoystickClose(joystick_);
            joystick_ = nullptr;
        }
    }

    void commitUrlEdit() {
        if (state_.urlBuffer.empty()) {
            state_.urlBuffer = state_.currentUrl;
            state_.inputMode = BrowserState::InputMode::None;
            updateTitle();
            return;
        }

        state_.currentUrl = normalizeUrl(state_.urlBuffer);
        state_.history.push_back(state_.currentUrl);
        state_.forwardStack.clear();
        state_.requestReload = true;
        state_.inputMode = BrowserState::InputMode::None;
        updateTitle();
    }

    static std::string normalizeUrl(std::string url) {
        auto hasScheme = url.find("://") != std::string::npos;
        if (!hasScheme) {
            url = "https://" + url;
        }
        return url;
    }

    void updateTitle() {
        std::string title;
        if (state_.inputMode == BrowserState::InputMode::Url) {
            title = "URL: " + state_.urlBuffer;
        } else if (state_.inputMode == BrowserState::InputMode::PageText) {
            title = "Type: " + state_.textBuffer;
        } else {
            title = "Page: " + state_.currentUrl;
        }
        SDL_SetWindowTitle(window_, title.c_str());
    }

    static std::array<uint8_t, 7> glyphFor(char ch) {
        switch (static_cast<unsigned char>(std::toupper(static_cast<unsigned char>(ch)))) {
        case 'A': return {14, 17, 17, 31, 17, 17, 17};
        case 'B': return {30, 17, 17, 30, 17, 17, 30};
        case 'C': return {14, 17, 16, 16, 16, 17, 14};
        case 'D': return {30, 17, 17, 17, 17, 17, 30};
        case 'E': return {31, 16, 16, 30, 16, 16, 31};
        case 'F': return {31, 16, 16, 30, 16, 16, 16};
        case 'G': return {14, 17, 16, 23, 17, 17, 15};
        case 'H': return {17, 17, 17, 31, 17, 17, 17};
        case 'I': return {31, 4, 4, 4, 4, 4, 31};
        case 'J': return {7, 2, 2, 2, 18, 18, 12};
        case 'K': return {17, 18, 20, 24, 20, 18, 17};
        case 'L': return {16, 16, 16, 16, 16, 16, 31};
        case 'M': return {17, 27, 21, 17, 17, 17, 17};
        case 'N': return {17, 25, 21, 19, 17, 17, 17};
        case 'O': return {14, 17, 17, 17, 17, 17, 14};
        case 'P': return {30, 17, 17, 30, 16, 16, 16};
        case 'Q': return {14, 17, 17, 17, 21, 18, 13};
        case 'R': return {30, 17, 17, 30, 20, 18, 17};
        case 'S': return {15, 16, 16, 14, 1, 1, 30};
        case 'T': return {31, 4, 4, 4, 4, 4, 4};
        case 'U': return {17, 17, 17, 17, 17, 17, 14};
        case 'V': return {17, 17, 17, 17, 17, 10, 4};
        case 'W': return {17, 17, 17, 17, 21, 21, 10};
        case 'X': return {17, 17, 10, 4, 10, 17, 17};
        case 'Y': return {17, 17, 10, 4, 4, 4, 4};
        case 'Z': return {31, 1, 2, 4, 8, 16, 31};
        case '0': return {14, 17, 19, 21, 25, 17, 14};
        case '1': return {4, 12, 4, 4, 4, 4, 14};
        case '2': return {14, 17, 1, 2, 4, 8, 31};
        case '3': return {30, 1, 1, 6, 1, 1, 30};
        case '4': return {2, 6, 10, 18, 31, 2, 2};
        case '5': return {31, 16, 16, 30, 1, 1, 30};
        case '6': return {14, 16, 16, 30, 17, 17, 14};
        case '7': return {31, 1, 2, 4, 8, 8, 8};
        case '8': return {14, 17, 17, 14, 17, 17, 14};
        case '9': return {14, 17, 17, 15, 1, 1, 14};
        case '-': return {0, 0, 0, 31, 0, 0, 0};
        case '.': return {0, 0, 0, 0, 0, 6, 6};
        case '/': return {1, 2, 2, 4, 8, 8, 16};
        case ':': return {0, 6, 6, 0, 6, 6, 0};
        case '_': return {0, 0, 0, 0, 0, 0, 31};
        case '?': return {14, 17, 1, 2, 4, 0, 4};
        case '@': return {14, 17, 1, 13, 21, 21, 14};
        case '&': return {12, 18, 20, 8, 21, 18, 13};
        case '=': return {0, 31, 0, 31, 0, 0, 0};
        case '+': return {0, 4, 4, 31, 4, 4, 0};
        case '#': return {10, 10, 31, 10, 31, 10, 10};
        case '%': return {24, 25, 2, 4, 8, 19, 3};
        case ' ': return {0, 0, 0, 0, 0, 0, 0};
        default: return {0, 0, 0, 0, 0, 0, 0};
        }
    }

    void drawGlyph(int x, int y, char ch, int scale, SDL_Color color) {
        SDL_SetRenderDrawColor(renderer_, color.r, color.g, color.b, color.a);
        const auto glyph = glyphFor(ch);
        for (int row = 0; row < 7; ++row) {
            for (int col = 0; col < 5; ++col) {
                if ((glyph[static_cast<size_t>(row)] >> (4 - col)) & 1U) {
                    SDL_Rect pixel{x + col * scale, y + row * scale, scale, scale};
                    SDL_RenderFillRect(renderer_, &pixel);
                }
            }
        }
    }

    void drawText(int x, int y, const std::string& text, int scale, SDL_Color color) {
        int cursor = x;
        for (char ch : text) {
            drawGlyph(cursor, y, ch, scale, color);
            cursor += scale * 6;
        }
    }

    void renderKeyboardOverlay(int width, int height) {
        if (!hasActiveKeyboard()) {
            return;
        }

        SDL_SetRenderDrawBlendMode(renderer_, SDL_BLENDMODE_BLEND);

        const auto overlayY = height / 2;
        SDL_Rect overlay{16, overlayY, width - 32, height - overlayY - 16};
        SDL_SetRenderDrawColor(renderer_, 11, 15, 23, 225);
        SDL_RenderFillRect(renderer_, &overlay);

        SDL_Color textColor{235, 239, 247, 255};
        SDL_Color accent{88, 166, 255, 255};
        const std::string header = state_.inputMode == BrowserState::InputMode::Url
                                       ? "URL INPUT"
                                       : "TEXT INPUT";
        drawText(overlay.x + 12, overlay.y + 12, header, 2, accent);

        std::string preview = activeBuffer();
        if (preview.size() > 40) {
            preview = preview.substr(preview.size() - 40);
        }
        drawText(overlay.x + 12, overlay.y + 36, preview, 2, textColor);

        const auto& layout = keyboardLayout();
        int y = overlay.y + 70;
        for (size_t rowIndex = 0; rowIndex < layout.size(); ++rowIndex) {
            const auto& row = layout[rowIndex];
            int x = overlay.x + 12;
            for (size_t colIndex = 0; colIndex < row.size(); ++colIndex) {
                const auto& key = row[colIndex];
                int keyWidth = static_cast<int>(std::max<size_t>(42, std::strlen(key.label) * 14 + 18));
                SDL_Rect keyRect{x, y, keyWidth, 34};
                bool selected = static_cast<int>(rowIndex) == state_.keyboardRow &&
                                static_cast<int>(colIndex) == state_.keyboardCol;
                SDL_SetRenderDrawColor(renderer_,
                                       selected ? 88 : 33,
                                       selected ? 166 : 43,
                                       selected ? 255 : 58,
                                       selected ? 255 : 235);
                SDL_RenderFillRect(renderer_, &keyRect);
                drawText(keyRect.x + 8, keyRect.y + 10, key.label, 2, selected ? SDL_Color{15, 20, 28, 255} : textColor);
                x += keyWidth + 8;
            }
            y += 42;
        }
    }

    void renderFrame() {
        int width = 0;
        int height = 0;
        SDL_GetWindowSize(window_, &width, &height);

        SDL_SetRenderDrawColor(renderer_, 20, 24, 31, 255);
        SDL_RenderClear(renderer_);

        // If we have a framebuffer, create/update texture and display it
        if (!framebuffer_.data.empty()) {
            // Create texture if needed or if size changed
            if (framebufferTexture_ == nullptr || 
                framebuffer_.width != width || framebuffer_.height != height) {
                if (framebufferTexture_ != nullptr) {
                    SDL_DestroyTexture(framebufferTexture_);
                }
                framebufferTexture_ = SDL_CreateTexture(
                    renderer_,
                    SDL_PIXELFORMAT_RGBA8888,
                    SDL_TEXTUREACCESS_STREAMING,
                    framebuffer_.width,
                    framebuffer_.height);
            }

            // Update texture with framebuffer data (using delta encoding for performance)
            if (framebufferTexture_ != nullptr) {
                if (framebuffer_.dirty) {
                    auto& dirtyRect = framebuffer_.dirtyRect;
                    
                    // If dirty rect is full screen, update entire texture
                    if (dirtyRect.w == framebuffer_.width && dirtyRect.h == framebuffer_.height) {
                        SDL_UpdateTexture(framebufferTexture_, nullptr, 
                                        framebuffer_.data.data(), 
                                        framebuffer_.width * 4);
                    } else {
                        // Update only the dirty region (delta encoding)
                        SDL_Rect updateRect{dirtyRect.x, dirtyRect.y, dirtyRect.w, dirtyRect.h};
                        size_t pixelOffset = (dirtyRect.y * framebuffer_.width + dirtyRect.x) * 4;
                        SDL_UpdateTexture(framebufferTexture_, &updateRect,
                                        framebuffer_.data.data() + pixelOffset,
                                        framebuffer_.width * 4);
                    }
                    
                    framebuffer_.dirty = false;
                }
                
                SDL_Rect dest{0, 0, width, height};
                SDL_RenderCopy(renderer_, framebufferTexture_, nullptr, &dest);
            }
        }

        if (state_.showUi || state_.inputMode != BrowserState::InputMode::None) {
            // Draw UI overlays
            SDL_Rect topBar{0, 0, width, std::max(44, height / 12)};
            SDL_SetRenderDrawColor(renderer_, 40, 58, 82, 200);
            SDL_RenderFillRect(renderer_, &topBar);

            // URL display in top bar
            SDL_Rect urlDisplay{12, topBar.y + 8, width - 24, topBar.h - 16};
            SDL_SetRenderDrawColor(renderer_, 30, 34, 44, 255);
            SDL_RenderFillRect(renderer_, &urlDisplay);

            std::string titleText;
            if (state_.inputMode == BrowserState::InputMode::Url) {
                titleText = "URL: " + state_.urlBuffer;
            } else if (state_.inputMode == BrowserState::InputMode::PageText) {
                titleText = "Type: " + state_.textBuffer;
            } else {
                titleText = "Page: " + state_.currentUrl;
            }
            
            if (titleText.length() > static_cast<size_t>(width / 14)) {
                titleText = titleText.substr(0, width / 14 - 3) + "...";
            }
            drawText(urlDisplay.x + 8, urlDisplay.y + 6, titleText, 2, SDL_Color{235, 239, 247, 255});

            // Render status indicators at the bottom
            SDL_Rect statusBar{0, height - 40, width, 40};
            SDL_SetRenderDrawColor(renderer_, 40, 58, 82, 150);
            SDL_RenderFillRect(renderer_, &statusBar);

            drawText(statusBar.x + 12, statusBar.y + 12, "A:Click  B:Back  X:Reload  Y:URL  L1:Keyboard  R1:HideUI", 2, SDL_Color{235, 239, 247, 255});
        }

        renderKeyboardOverlay(width, height);

        SDL_RenderPresent(renderer_);
    }

    BrowserState state_;
    Framebuffer framebuffer_;
    SDL_Texture* framebufferTexture_{nullptr};
    SDL_Window* window_{nullptr};
    SDL_Renderer* renderer_{nullptr};
    SDL_GameController* controller_{nullptr};
    SDL_Joystick* joystick_{nullptr};
    FirefoxProcessBackend backend_;
};

} // namespace

int main(int argc, char** argv) {
    // Initialize logging system (can be overridden with FIRE4ARKOS_LOG)
    initLogging();
    std::cout << "Fire4ArkOS Browser v1.1\n";
    logInfo("Fire4ArkOS Browser v1.1 started");

    LaunchOptions options;
    if (argc > 1 && argv[1] != nullptr && std::strlen(argv[1]) > 0) {
        options.initialUrl = argv[1];
    }
    if (argc > 0 && argv[0] != nullptr) {
        options.executablePath = argv[0];
    }

    App app(options);
    if (!app.initialize()) {
        app.shutdown();
        return 1;
    }

    app.run();
    app.shutdown();
    return 0;
}
