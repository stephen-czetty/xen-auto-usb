#include <unistd.h>
#include <string.h>
#include <stdio.h>
#include <sys/types.h>
#include <linux/limits.h>

int main(int argc, char *argv[])
{
    const char *scriptName = "auto-usb-attach.py";
    const char *environmentVariable = "WRAPPER";
    const char *sudoUidVariable = "SUDO_UID";
    char scriptPath[PATH_MAX];
    char wrapperPath[PATH_MAX];

    /* /proc/self/exe is a symlink to this executable */
    readlink("/proc/self/exe", wrapperPath, PATH_MAX);
    strcpy(scriptPath, wrapperPath);
    char *lastSlashPos = strrchr(scriptPath, '/');

    if (lastSlashPos - scriptPath + strlen(scriptName) > PATH_MAX-1)
    {
	    printf("Path too long, exiting.\n");
        return 0;
    }

    strcpy(lastSlashPos+1, scriptName);

    char env[strlen(wrapperPath) + strlen(environmentVariable) + 2];
    sprintf(env, "%s=%s", environmentVariable, wrapperPath);
    char sudoUidEnv[strlen(sudoUidVariable) + 12];
    sprintf(sudoUidEnv, "%s=%d", sudoUidVariable, getuid());
    /*setreuid(geteuid(), geteuid());*/
    char *environ[] = { env, sudoUidEnv, NULL };
    return execve(scriptPath, argv, environ);
}
