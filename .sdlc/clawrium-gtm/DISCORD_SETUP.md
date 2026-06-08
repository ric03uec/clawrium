# Discord Bot Setup — clawrium-gtm

**Channel**: `#announcements` · ID `1494197384094416906`
**Server**: Clawrium Discord server

---

## Step 1 — Create the application

1. Open https://discord.com/developers/applications
2. Click **New Application** (top right)
3. Name: `clawrium-gtm`
4. Click **Create**

## Step 2 — Create the bot user

1. In the left sidebar click **Bot**
2. Click **Add Bot** → **Yes, do it!**
3. Under **Username**, set it to `clawrium-gtm` if not already set
4. Under **Privileged Gateway Intents**, enable:
   - **Message Content Intent** (required for hermes to read message bodies)
   - **Server Members Intent** (required for hermes allowlist checks)
5. Click **Save Changes**

## Step 3 — Copy the bot token

1. Still on the **Bot** page, click **Reset Token** → confirm
2. Copy the token — you will only see it once
3. Store it:
   ```bash
   clawctl secret set wolf-i clawrium-gtm DISCORD_BOT_TOKEN
   # paste the token when prompted
   ```

## Step 4 — Invite the bot to the server

1. In the left sidebar click **OAuth2 → URL Generator**
2. Under **Scopes** check: `bot`
3. Under **Bot Permissions** check:
   - View Channels
   - Send Messages
   - Read Message History
   - Add Reactions
4. Copy the generated URL, open it in a browser
5. Select the **Clawrium** server → **Authorise**

## Step 5 — Lock bot to #announcements only

Goal: bot can see and post in `#announcements` and nowhere else.

**5a. Remove default server-level view access**
1. Server Settings → **Roles**
2. Find the role named `clawrium-gtm` (auto-created when bot joined)
3. Under **General Permissions**, turn OFF **View Channels**
4. Save — bot is now invisible to all channels by default

**5b. Grant access to #announcements only**
1. Open `#announcements` → click the gear icon (Edit Channel)
2. Go to **Permissions** tab
3. Click **+** → search for `clawrium-gtm` (the role, not the bot user)
4. Set:
   - ✅ View Channel
   - ✅ Send Messages
   - ✅ Read Message History
5. Save Changes

Bot will now only appear in `#announcements` and cannot read or post elsewhere.

## Step 6 — Verify

After the agent is created and started:
```bash
clawctl agent chat clawrium-gtm
# type: hello
# expect: a response from the agent
```

Then check `#announcements` on Discord — the bot should appear online.

---

## Reference

- App ID: `1513396778165080064`
- Token registered as channel: `discord-clawrium-gtm`
- Allowed channel: `1494197384094416906` (`#announcements`)
- Status: channel registered ✓
