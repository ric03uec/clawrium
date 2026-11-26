import { open, realpath } from "node:fs/promises";
import { createServer } from "node:http";
import { extname, isAbsolute, join, normalize, relative, resolve, sep } from "node:path";
import { pathToFileURL } from "node:url";

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".txt": "text/plain; charset=utf-8",
  ".webp": "image/webp",
  ".woff2": "font/woff2",
};

function sendText(response, status, body) {
  if (response.headersSent) {
    response.destroy();
    return;
  }
  response.writeHead(status, { "content-type": "text/plain; charset=utf-8" });
  response.end(body);
}

function requestPath(requestUrl) {
  if (!requestUrl?.startsWith("/") || requestUrl.startsWith("//")) {
    throw new URIError("Request target must be an origin-form path");
  }

  const rawPathname = requestUrl.split(/[?#]/, 1)[0];
  const decoded = decodeURIComponent(rawPathname).replaceAll("\\", "/");
  if (decoded.split("/").includes("..")) {
    throw new URIError("Path traversal is not allowed");
  }

  // A fixed base parses query/hash syntax without trusting the request Host header.
  return new URL(requestUrl, "http://127.0.0.1").pathname;
}

function remainsWithin(root, candidate) {
  const offset = relative(root, candidate);
  return offset === "" || (!offset.startsWith(`..${sep}`) && offset !== ".." && !isAbsolute(offset));
}

async function exportedPath(realRoot, pathname) {
  const decoded = decodeURIComponent(pathname);
  const relativePath = normalize(decoded).replace(/^([/\\])+/, "");
  const direct = resolve(realRoot, relativePath);
  if (!remainsWithin(realRoot, direct)) return null;

  const candidates = [direct];
  if (pathname === "/") {
    candidates.push(join(realRoot, "index.html"));
  } else if (!extname(relativePath)) {
    candidates.push(`${direct}.html`, join(direct, "index.html"));
  }

  for (const candidate of candidates) {
    let handle;
    try {
      const resolvedCandidate = await realpath(candidate);
      if (!remainsWithin(realRoot, resolvedCandidate)) continue;
      handle = await open(resolvedCandidate, "r");
      const stats = await handle.stat();
      if (!stats.isFile()) {
        await handle.close();
        continue;
      }
      return { handle, path: resolvedCandidate };
    } catch (error) {
      await handle?.close().catch(() => undefined);
      if (error?.code !== "ENOENT" && error?.code !== "ENOTDIR" && error?.code !== "EACCES") {
        throw error;
      }
    }
  }

  return null;
}

export async function createExportServer({ root }) {
  const realRoot = await realpath(resolve(root));

  return createServer(async (request, response) => {
    let pathname;
    try {
      pathname = requestPath(request.url);
    } catch {
      sendText(response, 400, "Bad request");
      return;
    }

    let exported;
    try {
      exported = await exportedPath(realRoot, pathname);
    } catch {
      sendText(response, 500, "Internal server error");
      return;
    }

    if (!exported) {
      sendText(response, 404, "Not found");
      return;
    }

    const stream = exported.handle.createReadStream();
    stream.on("error", () => sendText(response, 500, "Internal server error"));
    response.on("close", () => stream.destroy());
    response.writeHead(200, {
      "cache-control": "no-store",
      "content-type": contentTypes[extname(exported.path)] ?? "application/octet-stream",
    });
    stream.pipe(response);
  });
}

async function main() {
  const root = resolve(process.cwd(), process.env.PLAYWRIGHT_EXPORT_DIR ?? "out");
  const port = Number(process.env.PORT ?? 4173);
  const server = await createExportServer({ root });
  server.listen(port, "127.0.0.1", () => {
    console.log(`Serving ${root} at http://127.0.0.1:${port}`);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
  });
}
