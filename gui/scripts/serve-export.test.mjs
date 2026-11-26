import assert from "node:assert/strict";
import { mkdtemp, mkdir, rm, symlink, writeFile } from "node:fs/promises";
import { request } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { createExportServer } from "./serve-export.mjs";

let tempDir;
let root;
let server;
let port;

function get(path, headers = {}) {
  return new Promise((resolve, reject) => {
    const outgoing = request(
      { host: "127.0.0.1", port, path, headers },
      (response) => {
        const chunks = [];
        response.on("data", (chunk) => chunks.push(chunk));
        response.on("end", () =>
          resolve({
            body: Buffer.concat(chunks).toString("utf8"),
            headers: response.headers,
            status: response.statusCode,
          }),
        );
      },
    );
    outgoing.on("error", reject);
    outgoing.end();
  });
}

before(async () => {
  tempDir = await mkdtemp(join(tmpdir(), "clawrium-export-server-"));
  root = join(tempDir, "out");
  await mkdir(join(root, "_next", "static"), { recursive: true });
  await writeFile(join(root, "index.html"), "home");
  await writeFile(join(root, "agents.html"), "agents");
  await writeFile(join(root, "_next", "static", "app.js"), "asset");
  await writeFile(join(tempDir, "secret.txt"), "secret");
  await symlink(join(tempDir, "secret.txt"), join(root, "escape.txt"));

  server = await createExportServer({ root });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  port = server.address().port;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await rm(tempDir, { recursive: true, force: true });
});

test("serves clean routes and static assets without trusting Host", async () => {
  const route = await get("/agents", { host: "attacker.invalid" });
  assert.equal(route.status, 200);
  assert.equal(route.body, "agents");
  assert.equal(route.headers["content-type"], "text/html; charset=utf-8");

  const asset = await get("/_next/static/app.js");
  assert.equal(asset.status, 200);
  assert.equal(asset.body, "asset");
  assert.equal(asset.headers["content-type"], "text/javascript; charset=utf-8");
});

test("returns 400 for malformed percent encoding", async () => {
  const response = await get("/%ZZ");
  assert.equal(response.status, 400);
  assert.equal(response.body, "Bad request");
});

test("returns 400 for encoded traversal", async () => {
  const response = await get("/%2e%2e/secret.txt");
  assert.equal(response.status, 400);
  assert.equal(response.body, "Bad request");
});

test("does not follow symlinks outside the real export root", async () => {
  const response = await get("/escape.txt");
  assert.equal(response.status, 404);
  assert.equal(response.body, "Not found");
});
