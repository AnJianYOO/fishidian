/**
 * 小鱼界面插件 —— 宿主侧（Node）。
 * 本插件只贡献浏览器端外观；这里留一个探针，用来确认宿主导入过程是否真的走到本包。
 * 探针只写一行本地日志，不影响任何功能，删掉也不影响插件工作。
 */
import { appendFileSync } from "node:fs";
import { join } from "node:path";
import { homedir } from "node:os";

function apply(ctx) {
	try {
		const logPath = join(homedir(), ".dsh", "fatfish-ui-load.log");
		appendFileSync(
			logPath,
			`${new Date().toISOString()} apply-called pid=${process.pid}\n`
		);
	} catch (err) {
		/* 探针失败不影响插件 */
	}
	void ctx;
}

export { apply };
