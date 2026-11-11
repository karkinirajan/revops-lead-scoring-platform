import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";

// jsdom tests render with Testing Library: clean up between tests and add the DOM matchers. Node-environment tests skip both.
afterEach(async () => {
  if (typeof document !== "undefined") {
    const { cleanup } = await import("@testing-library/react");
    cleanup();
  }
});
