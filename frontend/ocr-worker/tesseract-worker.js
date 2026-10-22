/**
 * Classic worker wrapper for Tesseract (S3-T5 AC2, threat model T9).
 *
 * The page CSP requires Trusted Types, and `importScripts` is a sink in a
 * worker too. This wrapper installs the same `default` policy as
 * `src/ocr/trustedTypes.ts` (createScriptURL only, exact URL list) and then
 * loads the real Tesseract worker. `scripts/copy-ocr-assets.mjs` copies this
 * file to `public/ocr/tesseract-worker.js`. Keep ALLOWED equal to
 * `ALLOWED_SCRIPT_URLS` in `src/ocr/assets.ts` (a test checks it).
 */
(function () {
  var ALLOWED = [
    "/ocr/tesseract-worker.js",
    "/ocr/worker.min.js",
    "/ocr/tesseract-core/tesseract-core-lstm.wasm.js",
    "/ocr/tesseract-core/tesseract-core-simd-lstm.wasm.js",
    "/ocr/tesseract-core/tesseract-core-relaxedsimd-lstm.wasm.js",
  ];

  function isAllowed(input) {
    if (ALLOWED.indexOf(input) !== -1) {
      return true;
    }
    var origin = self.location.origin;
    return input.indexOf(origin) === 0 && ALLOWED.indexOf(input.slice(origin.length)) !== -1;
  }

  if (self.trustedTypes) {
    self.trustedTypes.createPolicy("default", {
      createScriptURL: function (input) {
        if (!isAllowed(input)) {
          throw new TypeError("Script URL is not allowed.");
        }
        return input;
      },
    });
  }

  importScripts("/ocr/worker.min.js");
})();
