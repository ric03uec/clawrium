#!/usr/bin/env node
/**
 * OpenClaw Device Pairing Script
 *
 * Uses bootstrap token for simplified localhost auto-pairing.
 *
 * Negotiates gateway protocol v3..v4 (issue #608) so the same script works
 * against v2026.4.2 (v3-only) and v2026.5.28+ (v4-only) daemons. Signature
 * payload schemas v2 and v3 are both selectable via a function table —
 * default is v2 because both daemon versions accept it (v4 daemon tries v3
 * then falls back to v2). Bumping to a v3-payload default is a follow-up
 * once v3-only daemons exist in the field.
 *
 * Usage: node pair_device.mjs <gateway_url> <bootstrap_token>
 * Output: JSON with deviceId, deviceToken, privateKeyPem
 */

import WebSocket from 'ws';
import crypto from 'crypto';

const [,, gatewayUrl, bootstrapToken] = process.argv;

const MIN_SUPPORTED_PROTOCOL = 3;
const MAX_SUPPORTED_PROTOCOL = 4;
const DEFAULT_PAYLOAD_VERSION = 'v2';

if (!gatewayUrl || !bootstrapToken) {
  console.error(JSON.stringify({
    error: 'Missing required arguments',
    usage: 'node pair_device.mjs <gateway_url> <bootstrap_token>'
  }));
  process.exit(1);
}

function generateDeviceKeypair() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519', {
    publicKeyEncoding: { type: 'spki', format: 'der' },
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' }
  });
  const rawPublicKey = publicKey.slice(-32);
  const publicKeyB64 = rawPublicKey.toString('base64url');
  const deviceId = crypto.createHash('sha256').update(rawPublicKey).digest('hex');
  return { deviceId, publicKeyB64, privateKeyPem: privateKey };
}

// Function table keyed by payload schema version. The signature payload
// schema is an axis independent of the connect-protocol version negotiated
// with the daemon — selection here does NOT track the negotiated protocol.
// v2026.5.28's daemon verifies a v3 payload first and falls back to v2,
// while v2026.4.2 only understands v2. v2 is the only schema that works on
// both, so it is the static default. When v2 is dropped upstream, add the
// v3 builder back here and flip DEFAULT_PAYLOAD_VERSION.
const PAYLOAD_BUILDERS = {
  v2(p) {
    return [
      'v2',
      p.deviceId,
      p.clientId,
      p.clientMode,
      p.role,
      p.scopes.join(','),
      String(p.signedAtMs),
      p.token ?? '',
      p.nonce,
    ].join('|');
  },
};

function buildSignaturePayload(version, params) {
  const builder = PAYLOAD_BUILDERS[version];
  if (!builder) {
    throw new Error(`Unsupported signature payload version: ${version}`);
  }
  return builder(params);
}

function signPayload(privateKeyPem, payload) {
  const privateKey = crypto.createPrivateKey(privateKeyPem);
  const signature = crypto.sign(null, Buffer.from(payload), privateKey);
  return signature.toString('base64url');
}

function formatProtocolMismatch(details) {
  const expected = details?.expectedProtocol;
  return (
    `openclaw gateway rejected pair handshake: protocol mismatch ` +
    `(pair script supports v${MIN_SUPPORTED_PROTOCOL}-v${MAX_SUPPORTED_PROTOCOL}, ` +
    `daemon expected v${expected ?? '?'}). ` +
    `Bump pair_device.mjs MAX_SUPPORTED_PROTOCOL to match the daemon, ` +
    `or pin the openclaw manifest to a version this script supports.`
  );
}

async function pairDevice() {
  const { deviceId, publicKeyB64, privateKeyPem } = generateDeviceKeypair();

  return new Promise((resolve, reject) => {
    const ws = new WebSocket(gatewayUrl);
    let messageId = 0;
    const pendingRequests = new Map();
    let challengeNonce = null;

    function sendRequest(method, params = {}) {
      const id = `req_${++messageId}`;
      return new Promise((res, rej) => {
        pendingRequests.set(id, { resolve: res, reject: rej });
        const msg = JSON.stringify({ type: 'req', id, method, params });
        ws.send(msg);
      });
    }

    ws.on('open', () => {});

    ws.on('message', async (data) => {
      try {
        const msg = JSON.parse(data.toString());

        if (msg.type === 'event' && msg.event === 'connect.challenge') {
          challengeNonce = msg.payload?.nonce;

          if (!challengeNonce) {
            console.error(JSON.stringify({ error: 'No challenge nonce received from gateway' }));
            ws.close();
            reject(new Error('No challenge nonce received'));
            return;
          }

          const signedAt = Date.now();
          const clientId = 'cli';
          const clientMode = 'cli';
          const role = 'operator';
          const scopes = ['operator.read', 'operator.write', 'operator.pairing'];
          const payloadVersion = DEFAULT_PAYLOAD_VERSION;
          const payload = buildSignaturePayload(payloadVersion, {
            deviceId,
            clientId,
            clientMode,
            role,
            scopes,
            signedAtMs: signedAt,
            token: bootstrapToken,
            nonce: challengeNonce,
          });
          const signature = signPayload(privateKeyPem, payload);

          try {
            const result = await sendRequest('connect', {
              minProtocol: MIN_SUPPORTED_PROTOCOL,
              maxProtocol: MAX_SUPPORTED_PROTOCOL,
              client: {
                id: clientId,
                version: '1.0.0',
                platform: process.platform,
                mode: clientMode
              },
              role: role,
              scopes: scopes,
              caps: [],
              commands: [],
              permissions: {},
              auth: { token: bootstrapToken },
              locale: 'en-US',
              userAgent: 'clawrium/1.0.0',
              device: {
                id: deviceId,
                publicKey: publicKeyB64,
                signature: signature,
                signedAt: signedAt,
                nonce: challengeNonce
              }
            });

            const negotiated = result.negotiatedProtocol;
            if (typeof negotiated === 'number' && Number.isInteger(negotiated)) {
              if (negotiated < MIN_SUPPORTED_PROTOCOL || negotiated > MAX_SUPPORTED_PROTOCOL) {
                throw new Error(formatProtocolMismatch({ expectedProtocol: negotiated }));
              }
            }

            const deviceToken = result.auth?.deviceToken;
            if (typeof deviceToken !== 'string' || deviceToken.length === 0) {
              throw new Error('No deviceToken in connect response');
            }
            const output = {
              deviceId: deviceId,
              deviceToken: deviceToken,
              privateKeyPem: privateKeyPem
            };
            console.log(JSON.stringify(output));
            ws.close();
            resolve(output);
          } catch (err) {
            ws.close();
            reject(err);
          }
          return;
        }

        if (msg.type === 'res' && pendingRequests.has(msg.id)) {
          const { resolve, reject } = pendingRequests.get(msg.id);
          pendingRequests.delete(msg.id);

          if (msg.error || !msg.ok) {
            const errDetails = msg.error?.details ?? null;
            const detailCode = errDetails?.code;
            let message;
            if (detailCode === 'protocol-mismatch' || detailCode === 'PROTOCOL_MISMATCH') {
              message = formatProtocolMismatch(errDetails);
            } else {
              message = msg.error?.message || (typeof msg.error === 'string' ? msg.error : 'Request failed');
            }
            const err = new Error(message);
            err.details = errDetails;
            reject(err);
          } else {
            resolve(msg.payload || msg.result || {});
          }
        }
      } catch (err) {
        console.error(JSON.stringify({ error: 'Failed to parse gateway message', details: err.message }));
      }
    });

    ws.on('error', (err) => {
      console.error(JSON.stringify({ error: 'WebSocket error', details: err.message }));
      reject(err);
    });

    const timeoutHandle = setTimeout(() => {
      ws.close();
      reject(new Error('Pairing timeout'));
    }, 30000);

    ws.on('close', (code, reason) => {
      clearTimeout(timeoutHandle);
      for (const [, { reject }] of pendingRequests) {
        reject(new Error(`Connection closed: ${code} ${reason}`));
      }
    });
  });
}

pairDevice().then(
  () => process.exit(0),
  (err) => {
    console.error(JSON.stringify({ error: 'Pairing failed', details: err.message }));
    process.exit(1);
  }
);
