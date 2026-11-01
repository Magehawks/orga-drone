import js from "@eslint/js";
import globals from "globals";

const browserStudioFiles = ["src/orga_drone/static/js/studio/**/*.js"];
const nodeTestFiles = ["tests/js/**/*.test.js"];

export default [
  {
    ignores: [
      "node_modules/**",
      "src/orga_drone/static/vendor/**",
      "dist*/**",
      "build*/**",
      "releases/**",
    ],
  },
  js.configs.recommended,
  {
    files: browserStudioFiles,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.browser,
    },
    rules: {
      eqeqeq: "warn",
      "no-var": "error",
      "prefer-const": "warn",
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: nodeTestFiles,
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.node,
    },
    rules: {
      eqeqeq: "warn",
      "no-var": "error",
      "prefer-const": "warn",
      "no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },
  {
    files: ["eslint.config.js"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      globals: globals.node,
    },
  },
];
