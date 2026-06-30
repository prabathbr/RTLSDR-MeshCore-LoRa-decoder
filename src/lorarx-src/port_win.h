#ifndef PORT_WIN_H
#define PORT_WIN_H

#ifdef _WIN32

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <winsock2.h>
#include <ws2tcpip.h>
#include <io.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <direct.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>

#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif

#define PORT_WIN 1

#define read _read
#define write _write
#define close _close
#define access _access
#define unlink _unlink
#define lseek _lseek
#define open _open
#define creat _creat
#define dup _dup
#define dup2 _dup2
#define fileno _fileno
#define getcwd _getcwd
#define chdir _chdir
#define mkdir(path, mode) _mkdir(path)

#ifndef F_OK
#define F_OK 0
#endif
#ifndef O_RDONLY
#define O_RDONLY _O_RDONLY
#endif
#ifndef O_RDWR
#define O_RDWR _O_RDWR
#endif
#ifndef O_APPEND
#define O_APPEND _O_APPEND
#endif
#ifndef O_CREAT
#define O_CREAT _O_CREAT
#endif
#ifndef O_TRUNC
#define O_TRUNC _O_TRUNC
#endif
#ifndef O_BINARY
#define O_BINARY _O_BINARY
#endif
#ifndef O_LARGEFILE
#define O_LARGEFILE 0
#endif
#ifndef O_NONBLOCK
#define O_NONBLOCK 0x4000
#endif
#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif

#ifndef F_GETFL
#define F_GETFL 3
#endif
#ifndef F_SETFL
#define F_SETFL 4
#endif
#ifndef F_SETFD
#define F_SETFD 2
#endif

#define lseek64 _lseeki64

#ifndef off64_t
#define off64_t __int64
#endif
#ifndef fstat
#define fstat _fstat
#endif
#ifndef SOL_TCP
#define SOL_TCP IPPROTO_TCP
#endif
#ifndef TCP_KEEPIDLE
#define TCP_KEEPIDLE TCP_KEEPALIVE
#endif
#ifndef TCP_KEEPINTVL
#define TCP_KEEPINTVL 17
#endif
#ifndef TCP_KEEPCNT
#define TCP_KEEPCNT 16
#endif

#ifndef S_IFMT
#define S_IFMT _S_IFMT
#endif
#ifndef S_IFIFO
#define S_IFIFO _S_IFIFO
#endif
#ifndef S_IFCHR
#define S_IFCHR _S_IFCHR
#endif

#ifndef MSG_DONTWAIT
#define MSG_DONTWAIT 0
#endif
#ifndef MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif

#ifndef SIGPIPE
#define SIGPIPE 13
#endif

#define grantpt(fd) 0
#define unlockpt(fd) 0
#define ptsname_r(fd, name, len) (-1)

static inline int symlink(const char *existing, const char *newname)
{
    (void)existing;
    (void)newname;
    return -1;
}

static inline void usleep(unsigned usec)
{
    if (usec >= 1000U) {
        Sleep(usec / 1000U);
    } else if (usec > 0U) {
        Sleep(1);
    }
}

#include "dirent_win.h"

void port_win_init(void);
int port_win_is_stdio_path(const char fn[], uint32_t fn_len, int for_write);
int port_win_open_stdio(int for_write, int nonblock);

#ifdef fcntl
#undef fcntl
#endif
int fcntl(int fd, int cmd, ...);

#endif /* _WIN32 */
#endif /* PORT_WIN_H */
