import { start } from "./bootstrap";
import { installTrustedTypesPolicy } from "./ocr/trustedTypes";
import "./styles.css";

// First action at startup: the Trusted Types `default` policy must exist before
// any script URL is used (the CSP says `trusted-types default`). Idempotent.
installTrustedTypesPolicy();

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Root element #root is missing");
}
void start(container);
