#include <stdarg.h>
#include "port_win.h"

static int wsa_ready;

void port_win_init(void)
{
    WSADATA wsa;

    if (wsa_ready) {
        return;
    }
    if (WSAStartup(MAKEWORD(2, 2), &wsa) == 0) {
        wsa_ready = 1;
    }
    _setmode(_fileno(stdin), _O_BINARY);
    _setmode(_fileno(stdout), _O_BINARY);
    _setmode(_fileno(stderr), _O_TEXT);
}

int port_win_is_stdio_path(const char fn[], uint32_t fn_len, int for_write)
{
    (void)for_write;
    if (!fn || fn_len == 0) {
        return 0;
    }
    if (fn[0] == '-' && (fn_len == 1 || fn[1] == 0)) {
        return 1;
    }
    if (fn_len >= 10 && strncmp(fn, "/dev/stdin", 10) == 0) {
        return 1;
    }
    if (fn_len >= 11 && strncmp(fn, "/dev/stdout", 11) == 0) {
        return 1;
    }
    return 0;
}

int port_win_open_stdio(int for_write, int nonblock)
{
    FILE *stream;
    int fd;

    (void)nonblock;
    stream = for_write ? stdout : stdin;
    fd = _fileno(stream);
    _setmode(fd, _O_BINARY);
    return fd;
}

int fcntl(int fd, int cmd, ...)
{
    va_list ap;
    long arg;
    u_long mode;

    if (cmd == F_GETFL) {
        return 0;
    }
    if (cmd == F_SETFL) {
        va_start(ap, cmd);
        arg = va_arg(ap, long);
        va_end(ap);
        if (arg & O_NONBLOCK) {
            mode = 1;
            return ioctlsocket((SOCKET)fd, FIONBIO, &mode);
        }
        return 0;
    }
    if (cmd == F_SETFD) {
        return 0;
    }
    errno = EINVAL;
    return -1;
}
