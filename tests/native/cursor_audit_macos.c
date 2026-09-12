/* Test instrumentation only. Never shipped inside the course application.
 * Log and suppress cursor capture/warping so a regression cannot steal the
 * developer's real mouse while the live acceptance suite runs. */
#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>

extern int SDL_SetRelativeMouseMode(int enabled);
extern void SDL_WarpMouseInWindow(void *window, int x, int y);
#ifndef COURSE_CURSOR_AUDIT_NO_AUDIO
extern void *alcOpenDevice(const char *name);
#endif

static void record(const char *event)
{
    const char *path = getenv("COURSE_CURSOR_AUDIT_LOG");
    if (!path) return;
    FILE *f = fopen(path, "a");
    if (f) { fprintf(f, "%s\n", event); fclose(f); }
}

__attribute__((constructor)) static void loaded(void) { record("audit_loaded"); }

static int audited_relative(int enabled)
{
    if (enabled) { record("CAPTURE_REQUESTED"); return 0; }
    int (*original)(int) = dlsym(RTLD_NEXT, "SDL_SetRelativeMouseMode");
    return original ? original(0) : 0;
}

static void audited_warp(void *window, int x, int y)
{
    (void)window; (void)x; (void)y;
    record("WARP_REQUESTED");
}

#ifndef COURSE_CURSOR_AUDIT_NO_AUDIO
static void *silent_audio_device(const char *name)
{
    (void)name;
    record("AUDIO_DEVICE_BLOCKED");
    return NULL;
}
#endif

__attribute__((used)) static struct { const void *replacement; const void *original; }
interpose[] __attribute__((section("__DATA,__interpose"))) = {
    { (const void *)audited_relative, (const void *)SDL_SetRelativeMouseMode },
    { (const void *)audited_warp, (const void *)SDL_WarpMouseInWindow },
#ifndef COURSE_CURSOR_AUDIT_NO_AUDIO
    { (const void *)silent_audio_device, (const void *)alcOpenDevice }
#endif
};
