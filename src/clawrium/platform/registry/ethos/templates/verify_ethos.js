#!/usr/bin/env node
// Post-configure validator — run as agent user
// Runs `ethos doctor` and exits non-zero on failure.
const { execSync } = require('child_process');
try {
  execSync('ethos doctor', { stdio: 'inherit' });
  process.exit(0);
} catch (e) {
  console.error('ethos doctor failed:', e.message);
  process.exit(1);
}
