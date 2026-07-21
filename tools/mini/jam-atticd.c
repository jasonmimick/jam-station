/* jam-atticd — the attic shelf-server helper that holds Full Disk Access.
 *
 * Same story as jam-cdd, different volume: macOS blocks a background launchd job
 * from reading the AFP-mounted Time Capsule (/tmp/tc-afp) unless its program has
 * been granted access — and it fails SILENTLY: os.walk yields nothing, the catalog
 * is empty, a manual SSH run works fine. Grant THIS binary Full Disk Access
 * (System Settings → Privacy & Security → Full Disk Access → ~/bin/jam-atticd);
 * it runs attic-server.py as a child, which inherits the access.
 *
 * ATTIC_ROOTS / ATTIC_PORT come from the launchd plist and are inherited by the
 * child. PATH is pinned so the server can find ffmpeg (/usr/local/bin) for the
 * on-the-fly WMA transcode.
 *
 * Build:  clang -O2 -o ~/bin/jam-atticd jam-atticd.c
 */
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>

int main(void) {
    setenv("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);
    for (;;) {
        pid_t pid = fork();
        if (pid == 0) {
            execl("/usr/bin/python3", "python3",
                  "/Users/jason/business/jam-station/tools/attic-server.py", (char *)0);
            _exit(127);
        }
        if (pid > 0)
            waitpid(pid, NULL, 0);
        sleep(5);            /* the server should never exit; pause before retry */
    }
    return 0;
}
