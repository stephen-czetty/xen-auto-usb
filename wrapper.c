#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <sys/types.h>
#include <linux/limits.h>

int main(int argc, char *argv[]) {
    const char *scriptName = "auto-usb-attach.py";
    const char *environmentVariable = "WRAPPER";
    char scriptPath[PATH_MAX];
    char wrapperPath[PATH_MAX];

    /* /proc/self/exe is a symlink to this executable */
    readlink("/proc/self/exe", wrapperPath, PATH_MAX);
    strcpy(scriptPath, wrapperPath);
    char *lastSlashPos = strrchr(scriptPath, '/');

    if (lastSlashPos - scriptPath + strlen(scriptName) > PATH_MAX-1)
    {
	printf("%s\n", scriptPath);
	printf("Path too long: %ld\n", lastSlashPos - scriptPath + strlen(scriptName));
        return 0;
    }

    strcpy(lastSlashPos+1, scriptName);
    printf("%s", scriptPath);

    char env[strlen(wrapperPath) + strlen(environmentVariable) + 2];
    sprintf(env, "%s=%s", environmentVariable, wrapperPath);
    char *environ[] = { env, NULL };
    return execve(scriptName, argv, environ);
}
