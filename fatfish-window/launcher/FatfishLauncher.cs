using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

// 大肥鱼窗口启动器
// 因为 Windows 快捷方式无法携带环境变量，用这个 exe 代劳：
// 设置 DSH_HOME 指向独立数据根，再用独立 --user-data-dir 拉起 DSH。
// 退出码：0 成功 / 1 找不到 DSH / 2 启动失败 / 3 异常 / 9 环境变量缺失
public class FatfishLauncher
{
    [DllImport("kernel32.dll")]
    private static extern IntPtr GetConsoleWindow();

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    public static int Main()
    {
        try { File.WriteAllText(Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "launcher-alive.txt"), "alive " + DateTime.Now.ToString()); } catch { }

        // 先把自己的控制台窗口藏掉，双击时不闪黑框
        IntPtr h = GetConsoleWindow();
        if (h != IntPtr.Zero) ShowWindow(h, 0);

        string log = "";
        int rc = 0;
        string logPath = "";
        try
        {
            string profile = Environment.GetEnvironmentVariable("USERPROFILE");
            log += "profile=[" + profile + "]\r\n";
            if (string.IsNullOrEmpty(profile))
            {
                rc = 9;
            }
            else
            {
                logPath = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "launcher.log");
                string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
                string home = Path.Combine(profile, ".dsh-fatfish");
                string exe = Path.Combine(local, "Programs", "DeepSeek Harness", "DeepSeek Harness.exe");

                log += "exe=" + exe + "\r\n";
                log += "exists=" + File.Exists(exe) + "\r\n";

                if (!File.Exists(exe))
                {
                    rc = 1;
                }
                else
                {
                    string dataDir = Path.Combine(home, "electron-data");

                    // 用 cmd 的 start 拉起：等价于 PowerShell 里
                    //   $env:DSH_HOME=<home>; Start-Process <exe> -ArgumentList "--user-data-dir=<dataDir>"
                    // 这条路径已经实机验证过能起两个窗口；直接 Process.Start 会被 DSH 自行退出。
                    ProcessStartInfo psi = new ProcessStartInfo("cmd.exe");
                    psi.Arguments = "/c set \"DSH_HOME=" + home + "\" && start \"\" \"" + exe + "\" \"--user-data-dir=" + dataDir + "\"";
                    psi.UseShellExecute = false;
                    psi.CreateNoWindow = true;
                    psi.WorkingDirectory = profile;

                    Process p = Process.Start(psi);
                    log += "cmd started=" + (p == null ? "null" : p.Id.ToString()) + "\r\n";
                    if (p == null) rc = 2;
                }
            }
        }
        catch (Exception ex)
        {
            log += "ERROR: " + ex.ToString() + "\r\n";
            rc = 3;
        }

        try
        {
            if (logPath.Length > 0)
            {
                File.AppendAllText(logPath, log);
            }
        }
        catch { }

        return rc;
    }
}
