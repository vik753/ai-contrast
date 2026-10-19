import { start } from "./bootstrap";
import "./styles.css";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("Root element #root is missing");
}
void start(container);
