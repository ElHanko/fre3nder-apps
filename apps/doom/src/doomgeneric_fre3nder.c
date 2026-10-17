/*
 * Fre3nder X2000 framebuffer + USB keyboard backend for DoomGeneric.
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * No SDL, X server, mouse, touch controls, audio, or device privilege changes.
 * tty7 belongs to the platform Display Frontend API v1 manager.
 */

#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#include "doomgeneric.h"

#include <errno.h>
#include <fcntl.h>
#include <linux/fb.h>
#include <linux/input.h>
#include <linux/kd.h>
#include <linux/vt.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>
#include <dirent.h>

/* Compile with DOOMGENERIC_RESX=320 and DOOMGENERIC_RESY=200. */
#if DOOMGENERIC_RESX != 320 || DOOMGENERIC_RESY != 200
#error Fre3nder Doom backend requires 320x200 source resolution
#endif

#define DISPLAY_WIDTH 480
#define DISPLAY_HEIGHT 272
#define IMAGE_WIDTH 170
#define MAX_KEYBOARDS 8
#define KEY_QUEUE_SIZE 128
#define KEYBIT_BYTES ((KEY_MAX + 8) / 8)

static int vt_fd = -1;
static int fb_fd = -1;
static struct vt_mode original_vt;
static int original_kd_mode;
static int vt_mode_saved;
static int kd_mode_saved;
static unsigned char *fb;
static size_t fb_length;
static struct fb_var_screeninfo var;
static struct fb_fix_screeninfo fix;
static int keyboard_fds[MAX_KEYBOARDS];
static int keyboard_count;
static uint16_t key_queue[KEY_QUEUE_SIZE];
static unsigned int key_read, key_write;
static volatile sig_atomic_t release_pending, acquire_pending, terminate_pending;
static volatile sig_atomic_t vt_active;
static struct timespec start_time;

static void fail(const char *message)
{
    perror(message);
    exit(1);
}

static void signal_vt_release(int signum) { (void)signum; vt_active = 0; release_pending = 1; }
static void signal_vt_acquire(int signum) { (void)signum; acquire_pending = 1; }
static void signal_exit(int signum) { (void)signum; terminate_pending = 1; }

static void close_resources(void)
{
    int i;
    for (i = 0; i < keyboard_count; ++i)
        if (keyboard_fds[i] >= 0) close(keyboard_fds[i]);
    keyboard_count = 0;
    if (fb && fb != MAP_FAILED) {
        munmap(fb, fb_length);
        fb = NULL;
    }
    if (fb_fd >= 0) { close(fb_fd); fb_fd = -1; }
    if (vt_fd >= 0) {
        if (kd_mode_saved) ioctl(vt_fd, KDSETMODE, original_kd_mode);
        if (vt_mode_saved) ioctl(vt_fd, VT_SETMODE, &original_vt);
        close(vt_fd);
        vt_fd = -1;
    }
}

static void process_vt(void)
{
    if (terminate_pending) exit(0);
    if (release_pending) {
        release_pending = 0;
        key_read = key_write;
        if (ioctl(vt_fd, VT_RELDISP, 1) < 0)
            perror("doom: release VT");
    }
    if (acquire_pending) {
        acquire_pending = 0;
        if (ioctl(vt_fd, VT_RELDISP, VT_ACKACQ) < 0)
            perror("doom: acquire VT");
        else
            vt_active = 1;
    }
}

static int keyboard_like(int fd)
{
    unsigned long evbits[(EV_MAX + sizeof(unsigned long) * 8) /
                         (sizeof(unsigned long) * 8)] = {0};
    unsigned char keys[KEYBIT_BYTES] = {0};
    if (ioctl(fd, EVIOCGBIT(0, sizeof(evbits)), evbits) < 0 ||
        !(evbits[EV_KEY / (8 * sizeof(unsigned long))] &
          (1UL << (EV_KEY % (8 * sizeof(unsigned long))))))
        return 0;
    if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(keys)), keys) < 0)
        return 0;
    return (keys[KEY_A / 8] & (1U << (KEY_A % 8))) &&
           (keys[KEY_ENTER / 8] & (1U << (KEY_ENTER % 8)));
}

static void open_keyboards(void)
{
    DIR *dir;
    struct dirent *entry;
    const char *input_dir = "/dev/input";
    dir = opendir(input_dir);
    if (!dir) fail("doom: open /dev/input");
    while ((entry = readdir(dir)) != NULL) {
        char path[256];
        int fd;
        if (strncmp(entry->d_name, "event", 5) != 0 ||
            entry->d_name[5] == '\0' ||
            strspn(entry->d_name + 5, "0123456789") != strlen(entry->d_name + 5))
            continue;
        if (keyboard_count == MAX_KEYBOARDS) break;
        if (snprintf(path, sizeof(path), "%s/%s", input_dir, entry->d_name) >= (int)sizeof(path))
            continue;
        fd = open(path, O_RDONLY | O_NONBLOCK | O_CLOEXEC | O_NOFOLLOW);
        if (fd < 0) continue;
        if (keyboard_like(fd)) keyboard_fds[keyboard_count++] = fd;
        else close(fd);
    }
    closedir(dir);
    if (!keyboard_count) {
        fprintf(stderr, "doom: no readable USB keyboard evdev device (check input-group permissions)\n");
        exit(1);
    }
}

/* The numeric values below are the Doom key identifiers from doomkeys.h.
 * Separate names avoid collisions with Linux <linux/input-event-codes.h>.
 */
static unsigned char to_doom_key(unsigned short code)
{
    switch (code) {
    case KEY_ESC: return 27;
    case KEY_ENTER: case KEY_KPENTER: return 13;
    case KEY_BACKSPACE: return 0x7f;
    case KEY_TAB: return 9;
    case KEY_SPACE: return 0xa2;
    case KEY_LEFTCTRL: case KEY_RIGHTCTRL: return 0xa3;
    case KEY_LEFTSHIFT: case KEY_RIGHTSHIFT: return 0xb6;
    case KEY_LEFTALT: case KEY_RIGHTALT: return 0xb8;
    case KEY_UP: return 0xad;
    case KEY_DOWN: return 0xaf;
    case KEY_LEFT: return 0xac;
    case KEY_RIGHT: return 0xae;
    case KEY_F1: return 0xbb;
    case KEY_F2: return 0xbc;
    case KEY_F3: return 0xbd;
    case KEY_F4: return 0xbe;
    case KEY_F5: return 0xbf;
    case KEY_F6: return 0xc0;
    case KEY_F7: return 0xc1;
    case KEY_F8: return 0xc2;
    case KEY_F9: return 0xc3;
    case KEY_F10: return 0xc4;
    case KEY_MINUS: return '-';
    case KEY_EQUAL: return '=';
    case KEY_1: return '1'; case KEY_2: return '2';
    case KEY_3: return '3'; case KEY_4: return '4';
    case KEY_5: return '5'; case KEY_6: return '6';
    case KEY_7: return '7'; case KEY_8: return '8';
    case KEY_9: return '9'; case KEY_0: return '0';
    case KEY_Q: return 'q'; case KEY_W: return 'w';
    case KEY_E: return 'e'; case KEY_R: return 'r';
    case KEY_T: return 't'; case KEY_Y: return 'y';
    case KEY_U: return 'u'; case KEY_I: return 'i';
    case KEY_O: return 'o'; case KEY_P: return 'p';
    case KEY_A: return 'a'; case KEY_S: return 's';
    case KEY_D: return 'd'; case KEY_F: return 'f';
    case KEY_G: return 'g'; case KEY_H: return 'h';
    case KEY_J: return 'j'; case KEY_K: return 'k';
    case KEY_L: return 'l'; case KEY_Z: return 'z';
    case KEY_X: return 'x'; case KEY_C: return 'c';
    case KEY_V: return 'v'; case KEY_B: return 'b';
    case KEY_N: return 'n'; case KEY_M: return 'm';
    case KEY_COMMA: return ','; case KEY_DOT: return '.';
    case KEY_SLASH: return '/';
    default: return 0;
    }
}

static void queue_key(unsigned char key, int down)
{
    unsigned int next = (key_write + 1) % KEY_QUEUE_SIZE;
    if (next == key_read) key_read = (key_read + 1) % KEY_QUEUE_SIZE;
    key_queue[key_write] = (uint16_t)((down << 8) | key);
    key_write = next;
}

static void pump_keyboard(void)
{
    struct pollfd pfd[MAX_KEYBOARDS];
    int i, ready;
    process_vt();
    for (i = 0; i < keyboard_count; ++i) {
        pfd[i].fd = keyboard_fds[i];
        pfd[i].events = POLLIN;
        pfd[i].revents = 0;
    }
    ready = poll(pfd, (nfds_t)keyboard_count, 0);
    if (ready <= 0) return;
    for (i = 0; i < keyboard_count; ++i) {
        struct input_event ev;
        if (!(pfd[i].revents & POLLIN)) continue;
        while (read(pfd[i].fd, &ev, sizeof(ev)) == sizeof(ev)) {
            unsigned char key;
            if (!vt_active || ev.type != EV_KEY || ev.value > 1) continue;
            key = to_doom_key(ev.code);
            if (key) queue_key(key, ev.value != 0);
        }
    }
}

static uint32_t bitfield(unsigned int component, struct fb_bitfield field)
{
    uint32_t max;
    if (field.length == 0) return 0;
    max = (1U << field.length) - 1U;
    return (((component * max + 127U) / 255U) << field.offset);
}

void DG_DrawFrame(void)
{
    int x, y, left = (DISPLAY_WIDTH - IMAGE_WIDTH) / 2;
    pump_keyboard();
    if (!vt_active) return;
    for (x = left; x < left + IMAGE_WIDTH; ++x) {
        if (!vt_active) break;
        /* LV_DISP_ROT_90 equivalent: portrait orientation on a landscape fb. */
        int sy = (x - left) * DOOMGENERIC_RESY / IMAGE_WIDTH;
        unsigned char *column = fb + (size_t)(x + var.xoffset) * (var.bits_per_pixel / 8);
        for (y = 0; y < DISPLAY_HEIGHT; ++y) {
            int sx = (DISPLAY_HEIGHT - 1 - y) * DOOMGENERIC_RESX / DISPLAY_HEIGHT;
            uint32_t rgb = DG_ScreenBuffer[sy * DOOMGENERIC_RESX + sx];
            uint32_t pixel = bitfield((rgb >> 16) & 255, var.red) |
                             bitfield((rgb >> 8) & 255, var.green) |
                             bitfield(rgb & 255, var.blue);
            unsigned char *dst = column + (size_t)(y + var.yoffset) * fix.line_length;
            if (var.bits_per_pixel == 32) memcpy(dst, &pixel, 4);
            else {
                uint16_t pixel16 = (uint16_t)pixel;
                memcpy(dst, &pixel16, 2);
            }
        }
    }
}

void DG_Init(void)
{
    const char *vt_path = getenv("FRE3NDER_DISPLAY_VT");
    const char *fb_path = getenv("FRE3NDER_DISPLAY_FRAMEBUFFER");
    struct vt_mode mode;
    struct sigaction action = {0};
    size_t needed;

    if (!vt_path || strcmp(vt_path, "/dev/tty7") || !fb_path || !*fb_path) {
        fprintf(stderr, "doom: expected display API v1 tty7 and framebuffer\n");
        exit(1);
    }
    if (atexit(close_resources) != 0) exit(1);
    action.sa_handler = signal_vt_release;
    sigaction(SIGUSR1, &action, NULL);
    action.sa_handler = signal_vt_acquire;
    sigaction(SIGUSR2, &action, NULL);
    action.sa_handler = signal_exit;
    sigaction(SIGTERM, &action, NULL);
    sigaction(SIGINT, &action, NULL);

    if (setsid() < 0) fail("doom: setsid");
    vt_fd = open(vt_path, O_RDWR | O_CLOEXEC | O_NOCTTY);
    if (vt_fd < 0 || ioctl(vt_fd, TIOCSCTTY, 0) < 0) fail("doom: controlling tty");
    if (ioctl(vt_fd, VT_GETMODE, &original_vt) < 0) fail("doom: VT_GETMODE");
    vt_mode_saved = 1;
    if (ioctl(vt_fd, KDGETMODE, &original_kd_mode) < 0) fail("doom: KDGETMODE");
    kd_mode_saved = 1;
    mode = original_vt;
    mode.mode = VT_PROCESS;
    mode.relsig = SIGUSR1;
    mode.acqsig = SIGUSR2;
    if (ioctl(vt_fd, VT_SETMODE, &mode) < 0 ||
        ioctl(vt_fd, KDSETMODE, KD_GRAPHICS) < 0 ||
        ioctl(vt_fd, VT_ACTIVATE, 7) < 0 ||
        ioctl(vt_fd, VT_WAITACTIVE, 7) < 0)
        fail("doom: VT graphics handoff");
    vt_active = 1;

    fb_fd = open(fb_path, O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (fb_fd < 0 || ioctl(fb_fd, FBIOGET_VSCREENINFO, &var) < 0 ||
        ioctl(fb_fd, FBIOGET_FSCREENINFO, &fix) < 0)
        fail("doom: framebuffer open/info");
    if (var.xres != DISPLAY_WIDTH || var.yres != DISPLAY_HEIGHT ||
        (var.bits_per_pixel != 32 && var.bits_per_pixel != 16) ||
        var.red.length > 8 || var.green.length > 8 || var.blue.length > 8 ||
        var.red.offset + var.red.length > var.bits_per_pixel ||
        var.green.offset + var.green.length > var.bits_per_pixel ||
        var.blue.offset + var.blue.length > var.bits_per_pixel) {
        fprintf(stderr, "doom: unsupported framebuffer layout\n");
        exit(1);
    }
    needed = (size_t)(var.yoffset + DISPLAY_HEIGHT - 1) * fix.line_length +
             (size_t)(var.xoffset + DISPLAY_WIDTH) * (var.bits_per_pixel / 8);
    if (!fix.line_length || !fix.smem_len || needed > fix.smem_len) {
        fprintf(stderr, "doom: invalid framebuffer bounds\n");
        exit(1);
    }
    fb_length = fix.smem_len;
    fb = mmap(NULL, fb_length, PROT_READ | PROT_WRITE, MAP_SHARED, fb_fd, 0);
    if (fb == MAP_FAILED) fail("doom: mmap framebuffer");
    memset(fb, 0, fb_length);

    open_keyboards();
    if (clock_gettime(CLOCK_MONOTONIC, &start_time) < 0)
        fail("doom: clock_gettime");
}

void DG_SleepMs(uint32_t ms)
{
    struct timespec request = { (time_t)(ms / 1000), (long)(ms % 1000) * 1000000L };
    process_vt();
    nanosleep(&request, NULL);
}

uint32_t DG_GetTicksMs(void)
{
    struct timespec now;
    process_vt();
    clock_gettime(CLOCK_MONOTONIC, &now);
    return (uint32_t)((now.tv_sec - start_time.tv_sec) * 1000ULL +
                      (now.tv_nsec - start_time.tv_nsec) / 1000000LL);
}

int DG_GetKey(int *pressed, unsigned char *key)
{
    uint16_t value;
    pump_keyboard();
    if (key_read == key_write) return 0;
    value = key_queue[key_read];
    key_read = (key_read + 1) % KEY_QUEUE_SIZE;
    *pressed = value >> 8;
    *key = value & 255;
    return 1;
}

void DG_SetWindowTitle(const char *title) { (void)title; }

int main(int argc, char **argv)
{
    doomgeneric_Create(argc, argv);
    for (;;) doomgeneric_Tick();
}
