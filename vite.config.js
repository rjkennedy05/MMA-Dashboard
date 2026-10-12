import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const projectRoot = path.dirname(fileURLToPath(import.meta.url));

function localDataSync() {
  let run = null;

  function publicState() {
    return run ?? {
      running: false,
      startedAt: null,
      finishedAt: null,
      exitCode: null,
      error: "",
    };
  }

  function sendJson(response, statusCode, payload) {
    response.statusCode = statusCode;
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(payload));
  }

  function readJson(request) {
    return new Promise((resolve, reject) => {
      let body = "";
      request.on("data", (chunk) => {
        body += chunk;
        if (body.length > 4096) reject(new Error("Request body is too large."));
      });
      request.on("end", () => {
        try { resolve(body ? JSON.parse(body) : {}); }
        catch { reject(new Error("Invalid JSON request.")); }
      });
      request.on("error", reject);
    });
  }

  const scopeArguments = {
    all: ["--mode", "daily"],
    ufc: ["--mode", "daily", "--skip-pfl", "--skip-one", "--skip-lfa", "--skip-bkfc", "--skip-retention"],
    dwcs: ["--mode", "daily", "--skip-pfl", "--skip-one", "--skip-lfa", "--skip-bkfc", "--skip-retention"],
    pfl: ["--mode", "daily", "--skip-ufc", "--skip-one", "--skip-lfa", "--skip-bkfc", "--skip-stats", "--skip-retention"],
    one: ["--mode", "daily", "--skip-ufc", "--skip-pfl", "--skip-lfa", "--skip-bkfc", "--skip-stats", "--skip-retention"],
    lfa: ["--mode", "daily", "--skip-ufc", "--skip-pfl", "--skip-one", "--skip-bkfc", "--skip-stats", "--skip-retention"],
    bkfc: ["--mode", "daily", "--skip-ufc", "--skip-pfl", "--skip-one", "--skip-lfa", "--skip-stats", "--skip-retention"],
  };

  return {
    name: "mma-dashboard-local-data-sync",
    configureServer(server) {
      server.middlewares.use("/api/local-sync", async (request, response) => {
        if (request.method === "GET") {
          sendJson(response, 200, publicState());
          return;
        }

        if (request.method !== "POST") {
          sendJson(response, 405, { error: "Method not allowed." });
          return;
        }

        if (request.headers["x-mma-dashboard"] !== "1") {
          sendJson(response, 403, { error: "Local dashboard request required." });
          return;
        }

        if (run?.running) {
          sendJson(response, 409, run);
          return;
        }

        let requestBody;
        try {
          requestBody = await readJson(request);
        } catch (error) {
          sendJson(response, 400, { error: error.message });
          return;
        }
        const scope = String(requestBody.scope ?? "all").toLowerCase();
        if (!Object.hasOwn(scopeArguments, scope)) {
          sendJson(response, 400, { error: "Unsupported promotion refresh scope." });
          return;
        }

        const startedAt = new Date().toISOString();
        const pythonCommand = process.env.MMA_DASHBOARD_PYTHON || "python";
        const child = spawn(
          pythonCommand,
          [
            path.join("api", "sync", "weekly_sync.py"),
            ...scopeArguments[scope],
            "--requested-scope",
            scope,
          ],
          {
            cwd: projectRoot,
            env: {
              ...process.env,
              PYTHONIOENCODING: "utf-8",
              PYTHONUTF8: "1",
            },
            shell: false,
            stdio: ["ignore", "pipe", "pipe"],
          }
        );

        run = {
          running: true,
          startedAt,
          finishedAt: null,
          exitCode: null,
          error: "",
          scope,
          stage: "starting",
          stageLabel: "Starting refresh",
        };

        let stderr = "";
        let stdoutBuffer = "";
        child.stdout.on("data", (chunk) => {
          stdoutBuffer += chunk.toString("utf8");
          const lines = stdoutBuffer.split(/\r?\n/);
          stdoutBuffer = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("SYNC_STAGE=")) continue;
            try {
              const progress = JSON.parse(line.slice("SYNC_STAGE=".length));
              run = {
                ...run,
                stage: progress.stage,
                stageStatus: progress.status,
                stageLabel: progress.label,
                stageUpdatedAt: progress.at,
              };
            } catch {
              // Progress is optional; process completion remains authoritative.
            }
          }
        });
        child.stderr.on("data", (chunk) => {
          stderr = `${stderr}${chunk}`.slice(-4000);
        });

        child.on("error", (error) => {
          run = {
            ...run,
            running: false,
            finishedAt: new Date().toISOString(),
            exitCode: -1,
            error: error.message,
          };
        });

        child.on("close", (exitCode) => {
          run = {
            ...run,
            running: false,
            finishedAt: new Date().toISOString(),
            exitCode,
            error: exitCode === 0 ? "" : stderr.trim() || `Sync exited with code ${exitCode}.`,
            stage: "finished",
            stageLabel: exitCode === 0 ? "Refresh complete" : "Refresh finished with issues",
          };
        });

        sendJson(response, 202, run);
      });
    },
  };
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), localDataSync()],
})
