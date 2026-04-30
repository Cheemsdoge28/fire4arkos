/**
 * Firefox Viewport Culling Helper
 * 
 * This script should be injected into Firefox to aggressively cull DOM elements
 * that are outside the visible viewport, preventing memory exhaustion on infinite-scroll sites.
 * 
 * Usage: Include in Firefox extension or autorun script
 */

(function() {
    'use strict';

    const VIEWPORT_HEIGHT = window.innerHeight;
    const VIEWPORT_WIDTH = window.innerWidth;
    const CULL_THRESHOLD = VIEWPORT_HEIGHT * 2; // Elements 2+ viewports away

    let lastCullTime = 0;
    const CULL_INTERVAL = 5000; // Cull every 5 seconds

    /**
     * Recursively cull elements outside viewport
     */
    function cullOffscreenElements() {
        const now = performance.now();
        if (now - lastCullTime < CULL_INTERVAL) {
            return; // Rate limit culling
        }
        lastCullTime = now;

        try {
            // Get all elements with significant DOM footprint
            const elements = document.querySelectorAll(
                'div, article, section, main, aside, li, p, span[style*="display"], img[src]'
            );

            let culled = 0;
            elements.forEach((el) => {
                if (!el || !el.offsetParent) return;

                const rect = el.getBoundingClientRect();
                
                // Hide if far outside viewport
                if (rect.bottom < -CULL_THRESHOLD || rect.top > VIEWPORT_HEIGHT + CULL_THRESHOLD) {
                    // Mark as culled instead of removing (faster)
                    if (!el.dataset.culled) {
                        el.style.display = 'none';
                        el.dataset.culled = 'true';
                        culled++;
                    }
                } else {
                    // Restore if back in view
                    if (el.dataset.culled === 'true') {
                        el.style.display = '';
                        delete el.dataset.culled;
                    }
                }
            });

            if (culled > 10) {
                console.log(`[Fire4ArkOS] Culled ${culled} off-screen elements`);
            }
        } catch (e) {
            console.error('[Fire4ArkOS] Culling error:', e);
        }
    }

    /**
     * Lazy load images: don't render until visible
     */
    function lazyLoadImages() {
        const images = document.querySelectorAll('img:not([loading="lazy"])');
        images.forEach((img) => {
            if (!img.src && img.dataset.src) {
                img.loading = 'lazy';
            }
        });
    }

    /**
     * Prevent memory explosion from large animations
     */
    function optimizeAnimations() {
        // Get all animated elements
        const animated = document.querySelectorAll('*[style*="animation"], *[class*="animate"]');
        
        // Pause animations for off-screen elements
        animated.forEach((el) => {
            const rect = el.getBoundingClientRect();
            if (rect.bottom < 0 || rect.top > VIEWPORT_HEIGHT) {
                el.style.animationPlayState = 'paused';
            } else {
                el.style.animationPlayState = 'running';
            }
        });
    }

    /**
     * Monitor for infinite scroll and cull aggressively
     */
    function monitorInfiniteScroll() {
        const bodyHeight = document.body.scrollHeight;
        const scrollPos = window.scrollY || document.documentElement.scrollTop;

        // If page grew very large, cull aggressively
        if (bodyHeight > 50000) { // > 50KB of scroll
            console.log(`[Fire4ArkOS] Large page detected (${bodyHeight}px), aggressive culling enabled`);
            
            // Cull more aggressively for huge pages
            const aggressive = document.querySelectorAll('div, section, article, li');
            let culledCount = 0;
            
            aggressive.forEach((el) => {
                const rect = el.getBoundingClientRect();
                if (rect.bottom < -CULL_THRESHOLD * 1.5 || rect.top > VIEWPORT_HEIGHT + CULL_THRESHOLD * 1.5) {
                    if (!el.dataset.culled) {
                        el.style.display = 'none';
                        el.dataset.culled = 'true';
                        culledCount++;
                    }
                }
            });

            if (culledCount > 0) {
                console.log(`[Fire4ArkOS] Aggressively culled ${culledCount} elements`);
            }
        }
    }

    /**
     * Initialize viewport culling
     */
    function init() {
        console.log('[Fire4ArkOS] Viewport culling enabled');

        // Initial cull
        cullOffscreenElements();
        lazyLoadImages();

        // Setup scroll listener for continuous culling
        let scrollTimeout;
        window.addEventListener('scroll', () => {
            clearTimeout(scrollTimeout);
            scrollTimeout = setTimeout(() => {
                cullOffscreenElements();
                monitorInfiniteScroll();
            }, 100);
        });

        // Periodic culling even without scroll (for dynamic content)
        setInterval(() => {
            cullOffscreenElements();
            lazyLoadImages();
            optimizeAnimations();
        }, 5000);

        // Respond to window resize
        window.addEventListener('resize', () => {
            cullOffscreenElements();
        });

        // Watch for new elements added via AJAX
        const observer = new MutationObserver(() => {
            lazyLoadImages();
            monitorInfiniteScroll();
        });

        observer.observe(document.body, {
            childList: true,
            subtree: true,
            attributes: false,
            characterData: false,
        });

        console.log('[Fire4ArkOS] Viewport culling initialized');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
