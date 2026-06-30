#ifndef DIRENT_WIN_H
#define DIRENT_WIN_H

#ifdef _WIN32

#include <windows.h>
#include <stdio.h>

typedef struct DIR {
    HANDLE handle;
    WIN32_FIND_DATAA data;
    int first;
    char path[MAX_PATH];
} DIR;

struct dirent {
    char d_name[MAX_PATH];
};

typedef struct dirent dirent;

static inline DIR *opendir(const char *name)
{
    DIR *dir;
    size_t len;

    dir = (DIR *)malloc(sizeof(DIR));
    if (!dir) {
        return NULL;
    }
    len = strlen(name);
    if (len + 3 >= sizeof(dir->path)) {
        free(dir);
        return NULL;
    }
    memcpy(dir->path, name, len + 1);
    if (len == 0 || dir->path[len - 1] != '\\' && dir->path[len - 1] != '/') {
        strcat(dir->path, "\\*");
    } else {
        strcat(dir->path, "*");
    }
    dir->handle = FindFirstFileA(dir->path, &dir->data);
    dir->first = 1;
    if (dir->handle == INVALID_HANDLE_VALUE) {
        free(dir);
        return NULL;
    }
    return dir;
}

static inline struct dirent *readdir(DIR *dir)
{
    static struct dirent entry;

    if (!dir || dir->handle == INVALID_HANDLE_VALUE) {
        return NULL;
    }
    if (dir->first) {
        dir->first = 0;
    } else if (!FindNextFileA(dir->handle, &dir->data)) {
        return NULL;
    }
    strncpy(entry.d_name, dir->data.cFileName, sizeof(entry.d_name) - 1);
    entry.d_name[sizeof(entry.d_name) - 1] = '\0';
    return &entry;
}

static inline int closedir(DIR *dir)
{
    if (!dir) {
        return -1;
    }
    if (dir->handle != INVALID_HANDLE_VALUE) {
        FindClose(dir->handle);
    }
    free(dir);
    return 0;
}

#endif
#endif
