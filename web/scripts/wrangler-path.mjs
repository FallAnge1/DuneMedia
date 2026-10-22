// Путь к wrangler из node_modules. Запускаем его через node, а не через npx:
// на Windows Node.js не может запустить npx (npx.cmd) без оболочки, а оболочка ломает кавычки в SQL.
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);

export function wranglerArgs(args) {
  const pkg = require.resolve("wrangler/package.json");
  return [process.execPath, [join(dirname(pkg), "bin", "wrangler.js"), ...args]];
}
