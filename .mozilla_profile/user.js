user_pref("browser.startup.homepage", "about:blank");
user_pref("general.useragent.override", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36");
user_pref("layout.css.devPixelsPerPx", "1.000");
user_pref("toolkit.legacyUserProfileCustomizations.stylesheets", true);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("startup.homepage_welcome_url", "");
user_pref("startup.homepage_welcome_url.additional", "");
user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("toolkit.telemetry.reportingpolicy.firstRun", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.closeWindowWithLastTab", false);
user_pref("font.default.x-western", "sans-serif");
user_pref("font.name-list.sans-serif.x-western", "Noto Sans, Noto Sans CJK SC, Noto Sans CJK TC, Noto Sans CJK JP, Noto Sans CJK KR");
user_pref("toolkit.cosmeticAnimations.enabled", false);
user_pref("general.smoothScroll", false);
user_pref("network.http.max-connections", 48);
user_pref("network.http.max-persistent-connections-per-server", 6);
user_pref("network.http.max-urgent-unused-idle-connections", 0);
user_pref("network.dns.disablePrefetch", false);
user_pref("network.prefetch-next", true);

/* Cache: RAM (hot) + disk (cold, with limits) */
user_pref("browser.cache.disk.enable", true);
user_pref("browser.cache.disk.capacity", 131072);
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", 65536);
user_pref("browser.cache.memory.max_entry_size", 8192);
user_pref("browser.cache.disk.max_entry_size", 8192);
user_pref("browser.sessionstore.max_tabs_undo", 0);
user_pref("browser.sessionstore.max_windows_undo", 0);

/* Disable gamepad API to prevent Firefox from double-handling controller inputs */
user_pref("dom.gamepad.enabled", false);
user_pref("dom.gamepad.non_standard_events.enabled", false);

/* Disable touch and pointer events to force pure legacy mouse behavior */
user_pref("dom.w3c_touch_events.enabled", 0);
user_pref("dom.w3c_pointer_events.enabled", false);
    user_pref("dom.max_script_run_time", 30);
    user_pref("dom.max_chrome_script_run_time", 30);

/* Stability: Disable JIT on ARM to prevent random segfaults (rc=-11) */
user_pref("javascript.options.baselinejit", false);
user_pref("javascript.options.ion", false);
user_pref("javascript.options.asmjs", false);
user_pref("javascript.options.wasm", false);
user_pref("dom.ipc.processCount", 1);
user_pref("dom.ipc.processCount.extension", 1);

/* Reduce telemetry and background sync that cause writes */
user_pref("services.sync.enabled", false);
user_pref("toolkit.telemetry.enabled", false);
user_pref("datareporting.healthreport.uploadEnabled", false);
user_pref("app.update.enabled", false);

/* Audio: default to Firefox's backend selection unless explicitly overridden.
   On some devices ALSA is preferred; on desktop Linux Pulse/PipeWire often works better. */
user_pref("media.cubeb.sandbox", false);
user_pref("security.sandbox.content.level", 0);
user_pref("security.sandbox.audio.main.enabled", false);
user_pref("media.sandbox.content.level", 0);
user_pref("media.audioipc.enabled", false);
user_pref("media.cubeb.backend", "pulse");
user_pref("media.cubeb.output_sample_rate", 48000);
user_pref("media.cubeb.output_latency_ms", 100);
user_pref("media.volume_scale", "1.0");
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 0);
user_pref("media.cubeb.logging", true);
user_pref("media.cubeb.backend", "pulse");


/* UI Compactness and Scaling */
user_pref("browser.uidensity", 1); /* Compact mode to save vertical space */
user_pref("browser.compactmode.show", true);
user_pref("browser.tabs.drawInTitlebar", true);

/* Prevent jitter from dismissing menus (VERY IMPORTANT for handhelds) */
user_pref("ui.popup.disable_autohide", true);

/* --- MEDIA PERFORMANCE ---
   VP9 / WebM are software-decode only on this ARM SoC.
   Force H.264 (AVC) via MSE + system ffmpeg which has hardware-assisted paths. */
user_pref("media.mediasource.enabled", true);
user_pref("media.mediasource.mp4.enabled", true);
user_pref("media.mediasource.vp9.enabled", false);
user_pref("media.mediasource.webm.enabled", false);
user_pref("media.mediasource.vp9.implicit.enabled", false);
user_pref("media.mediasource.av1.enabled", false);
user_pref("media.av1.enabled", false);
user_pref("media.ffmpeg.enabled", true);
user_pref("media.ffmpeg.vaapi.enabled", true);
user_pref("media.ffvpx.enabled", false);
/* Allow autoplay so media with sound can start without requiring manual permission. */
user_pref("media.autoplay.default", 0);
user_pref("media.autoplay.blocking_policy", 2);
user_pref("media.memory_cache_max_size", 65536);
user_pref("media.cache_size", 524288);
user_pref("media.navigator.video.max_fps", 24);
user_pref("media.video-max-decode-error", 0);
user_pref("layers.acceleration.disabled", true);
user_pref("gfx.webrender.all", false);
user_pref("gfx.webrender.software", false);
user_pref("image.mem.decode_on_draw", true);
user_pref("browser.tabs.remote.autostart", false); /* Save RAM by disabling multi-process for single-tab use */

/* Prevent CPU stall on heavy pages: limit content processes + GC tuning */
user_pref("dom.ipc.processCount", 1);
user_pref("dom.ipc.processCount.webIsolated", 1);
user_pref("dom.ipc.processCount.file", 1);
user_pref("browser.tabs.remote.autostart", true);
user_pref("javascript.options.mem.gc_incremental", true);
user_pref("javascript.options.mem.gc_per_zone", true);
user_pref("javascript.options.mem.gc_incremental_slice_ms", 25);
user_pref("javascript.options.mem.high_water_mark", 64);
user_pref("javascript.options.mem.max", 196608);
user_pref("dom.ipc.tabs.shutdownTimeoutSecs", 5);

/* Ion JIT MUST be on — sites like Reddit use heavy React bundles.
   Baseline-only is 2-3x slower for hot JS loops. */
user_pref("javascript.options.baselinejit", true);
user_pref("javascript.options.ion", true);
user_pref("javascript.options.native_regexp", true);

/* Reduce reflow frequency during page load (less layout thrash) */
user_pref("content.notify.interval", 750000);

user_pref("image.downscale-during-decode.enabled", true);
user_pref("image.mem.surfacecache.max_size_kb", 8192);
user_pref("image.mem.discardable", true);
user_pref("image.mem.decode_bytes_at_a_time", 1024);
user_pref("image.multithreaded_decoding.limit", 1);
user_pref("image.high_quality_upscaling.enabled", false);
user_pref("image.high_quality_downscaling.enabled", false);
user_pref("image.animation_mode", "none");
user_pref("image.mem.min_discard_timeout_ms", 250);
user_pref("gfx.canvas.accelerated", false);
user_pref("layers.mlgpu.enabled", false);
user_pref("layers.offmainthreadcomposition.enabled", true);
user_pref("layers.async-pan-zoom.enabled", true);
user_pref("browser.low_commit_space_threshold_mb", 96);
user_pref("browser.sessionhistory.max_entries", 4);
user_pref("dom.image.lazy_loading.enabled", true);
user_pref("browser.tabs.max_memory_usage_mb", 256);
