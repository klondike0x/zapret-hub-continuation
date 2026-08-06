import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { initializeBridge } from "./bridge";
import "./styles.css";

await initializeBridge();

ReactDOM.createRoot(document.getElementById("root")!).render(<App />);
