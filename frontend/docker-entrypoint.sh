set -eu

node <<'NODE'
const fs = require("fs");

const apiBaseUrl =
  process.env.VALIDATOR_FRONTEND_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  "";

fs.writeFileSync(
  "/app/public/runtime-config.js",
  `window.__VALIDATOR_CONFIG__ = ${JSON.stringify({ apiBaseUrl })};\n`,
  "utf8",
);
NODE

exec "$@"
