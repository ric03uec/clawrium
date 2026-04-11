#!/usr/bin/env node
/**
 * OpenClaw Device Pairing Script (v2)
 *
 * Uses bootstrap token for simplified localhost auto-pairing.
 *
 * Usage: node pair_device.mjs <gateway_url> <bootstrap_token>
 * Output: JSON with deviceId, deviceToken, privateKeyPem
 */

import WebSocket from 'ws';
import crypto from 'crypto';

const [,, gatewayUrl, bootstrapToken] = process.argv;

if (!gatewayUrl || !bootstrapToken) {
  console.error(JSON.stringify({
    error: 'Missing required arguments',
    usage: 'node pair_device.mjs <gateway_url> <bootstrap_token>'
  }));
  process.exit(1);
}

// Generate Ed25519 keypair for device identity
function generateDeviceKeypair() {
  const { publicKey, privateKey } = crypto.generateKeyPairSync('ed25519', {
    publicKeyEncoding: { type: 'spki', format: 'der' },
    privateKeyEncoding: { type: 'pkcs8', format: 'pem' }
  });
  // Extract raw public key (last 32 bytes of DER)
  const rawPublicKey = publicKey.slice(-32);
  const publicKeyB64 = rawPublicKey.toString('base64url');
  // Device ID is hash of public key
  const deviceId = crypto.createHash('sha256').update(rawPublicKey).digest('hex');
  return { deviceId, publicKeyB64, privateKeyPem: privateKey };
}

// Sign challenge with private key using v2 payload format
function signChallenge(privateKeyPem, nonce, deviceId, signedAt, token, clientId, clientMode, role, scopes) {
  const privateKey = crypto.createPrivateKey(privateKeyPem);
  // v2 format: v2|deviceId|clientId|clientMode|role|scopes|signedAtMs|token|nonce
  const scopesStr = scopes.join(',');
  const payload = `v2|${deviceId}|${clientId}|${clientMode}|${role}|${scopesStr}|${signedAt}|${token}|${nonce}`;
  const signature = crypto.sign(null, Buffer.from(payload), privateKey);
  return signature.toString('base64url');
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

    ws.on('open', () => {
      // Wait for server challenge
    });

    ws.on('message', async (data) => {
      try {
        const msg = JSON.parse(data.toString());

        // Handle server challenge
        if (msg.type === 'event' && msg.event === 'connect.challenge') {
          challengeNonce = msg.payload?.nonce;

          const signedAt = Date.now();
          const clientId = 'cli';
          const clientMode = 'cli';
          const role = 'operator';
          const scopes = ['operator.read', 'operator.write', 'operator.pairing'];
          const signature = signChallenge(privateKeyPem, challengeNonce, deviceId, signedAt, bootstrapToken, clientId, clientMode, role, scopes);

          try {
            const result = await sendRequest('connect', {
              minProtocol: 3,
              maxProtocol: 3,
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

            // Check if we got a device token back
            if (result.auth?.deviceToken) {
              const output = {
                deviceId: deviceId,
                deviceToken: result.auth.deviceToken,
                privateKeyPem: privateKeyPem
              };
              console.log(JSON.stringify(output));
              ws.close();
              resolve(output);
            } else {
              throw new Error('No deviceToken in connect response');
            }
          } catch (err) {
            console.error(JSON.stringify({ error: err.message, details: err }));
            ws.close();
            reject(err);
          }
          return;
        }

        // Handle responses
        if (msg.type === 'res' && pendingRequests.has(msg.id)) {
          const { resolve, reject } = pendingRequests.get(msg.id);
          pendingRequests.delete(msg.id);

          if (msg.error || !msg.ok) {
            reject(new Error(msg.error?.message || msg.error || 'Request failed'));
          } else {
            resolve(msg.payload || msg.result || {});
          }
        }
      } catch (err) {
        // Ignore parse errors
      }
    });

    ws.on('error', (err) => {
      console.error(JSON.stringify({ error: 'WebSocket error', details: err.message }));
      reject(err);
    });

    ws.on('close', (code, reason) => {
      for (const [, { reject }] of pendingRequests) {
        reject(new Error(`Connection closed: ${code} ${reason}`));
      }
    });

    // Timeout after 30 seconds
    setTimeout(() => {
      ws.close();
      reject(new Error('Pairing timeout'));
    }, 30000);
  });
}

pairDevice().catch((err) => {
  console.error(JSON.stringify({ error: 'Pairing failed', details: err.message }));
  process.exit(1);
});
