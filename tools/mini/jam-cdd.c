/* jam-cdd — the CD-watch helper that holds Full Disk Access.
 *
 * macOS blocks a background launchd job from reading removable volumes (/Volumes/<a CD>)
 * unless it's granted access — and it fails SILENTLY, which is why the auto-watcher couldn't
 * see inserted discs while a manual (SSH) run could. The fix is to grant Full Disk Access to
 * the job's program. Rather than grant /bin/bash broadly, this tiny binary IS the program:
 * grant THIS one FDA. As the launchd job's responsible process it runs cd-tick.sh in-job every
 * 12s, so cd-tick / rip-cd / lame all inherit its access and can read the disc.
 *
 * CD_TICK_FOREGROUND=1 tells cd-tick to run the rip in the FOREGROUND (a child of this job, not
 * detached) so the ripper keeps the inherited access for the whole rip. One rip at a time, so
 * blocking here is fine.
 *
 * Build:  clang -O2 -o ~/bin/jam-cdd jam-cdd.c
 */
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>

int main(void) {
    setenv("CD_TICK_FOREGROUND", "1", 1);
    setenv("PATH", "/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin", 1);
    for (;;) {
        pid_t pid = fork();
        if (pid == 0) {
            execl("/bin/bash", "bash",
                  "/Users/jason/business/jam-station/tools/cd-tick.sh", (char *)0);
            _exit(127);
        }
        if (pid > 0)
            waitpid(pid, NULL, 0);
        sleep(12);
    }
    return 0;
}
