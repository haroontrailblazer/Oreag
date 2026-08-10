import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // The LikeC4 viewer, generated into public/ by the prebuild hook. It is
    // minified third-party output - one bundle is over 1MB - and linting it
    // does not merely waste time: ESLint collects a finding per line and then
    // dies formatting them, `RangeError: Invalid string length`.
    //
    // CI happens to survive this only because it lints BEFORE it builds, so
    // the directory does not exist yet. Locally, one `npm run build` makes
    // `npm run lint` crash from then on. ESLint's flat config does not read
    // .gitignore, so being gitignored is not enough.
    "public/architecture/**",
  ]),
]);

export default eslintConfig;
