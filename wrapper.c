#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <sys/types.h>
#include <linux/limits.h>

int main(int argc, char *argv[]) {
    const char *scriptName = "auto-usb-attach.py";
    char scriptPath[PATH_MAX];

    /* /proc/self/exe is a symlink to this executable */
    readlink("/proc/self/exe", scriptPath, PATH_MAX);
    char *lastSlashPos = strrchr(scriptPath, '/');

    if (lastSlashPos - scriptPath + strlen(scriptName) > PATH_MAX-1)
        return 0;

    strcpy(lastSlashPos+1, scriptName);
    printf("%s", scriptPath);


    char *emptyEnviron[] = { NULL };
    return execve(scriptName, argv, emptyEnviron);
}
