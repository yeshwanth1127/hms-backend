import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.tsx";
import { WorkspaceBoundary } from "./components/WorkspaceBoundary";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <WorkspaceBoundary>
      <App />
    </WorkspaceBoundary>
  </StrictMode>,
);
