// Test instrumentation only: never ship this in the student application.
#import <AppKit/AppKit.h>
#import <objc/runtime.h>
#include <stdio.h>
#include <stdlib.h>
static void logEvent(const char *event) {
 const char *path=getenv("COURSE_FOCUS_AUDIT_LOG");if(!path)return;
 FILE *f=fopen(path,"a");if(f){fprintf(f,"%s\n",event);fclose(f);}
}
static void suppressActivate(id self, SEL cmd, BOOL flag) { logEvent("APP_ACTIVATION_SUPPRESSED"); }
static BOOL suppressRunning(id self, SEL cmd, NSApplicationActivationOptions flags) { logEvent("RUNNING_ACTIVATION_SUPPRESSED");return NO; }
static void orderBehind(id self, SEL cmd, id sender) { logEvent("KEY_FRONT_SUPPRESSED");[(NSWindow*)self orderBack:nil]; }
static void suppressKey(id self, SEL cmd) { logEvent("KEY_WINDOW_SUPPRESSED"); }
static void replace(Class cls, SEL sel, IMP imp) {
 Method m=class_getInstanceMethod(cls,sel);if(m)method_setImplementation(m,imp);
}
__attribute__((constructor)) static void initFocusGuard(void) {
 if(!getenv("COURSE_TEST_BACKGROUND"))return;
 logEvent("focus_guard_loaded");
 replace([NSApplication class],@selector(activateIgnoringOtherApps:),(IMP)suppressActivate);
 replace([NSRunningApplication class],@selector(activateWithOptions:),(IMP)suppressRunning);
 replace([NSWindow class],@selector(makeKeyAndOrderFront:),(IMP)orderBehind);
 replace([NSWindow class],@selector(makeKeyWindow),(IMP)suppressKey);
}
