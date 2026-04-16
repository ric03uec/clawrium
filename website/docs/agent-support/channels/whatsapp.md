# WhatsApp

**Status:** 📋 Not Currently Planned

WhatsApp Business API integration for agent communication.

---

## Why Not Planned?

WhatsApp integration is not currently on the Clawrium roadmap for the following reasons:

1. **Complexity:** WhatsApp Business API requires Meta approval and business verification
2. **Cost:** Per-conversation pricing model
3. **Use Case:** Limited demand for WhatsApp automation in current user base
4. **Alternatives:** Discord and Slack cover most messaging needs
5. **Priority:** Development focused on Slack and Web channels first

---

## Want This Feature?

We welcome community contributions! If you need WhatsApp support:

### Option 1: Open an Issue

[Create a feature request](https://github.com/ric03uec/clawrium/issues/new?labels=enhancement,channel&title=Add+WhatsApp+channel+support)

Include:
- Your use case (personal, business, etc.)
- Expected volume of messages
- Whether you can contribute a PR

### Option 2: Submit a PR

We'd love your contribution! Implementation would involve:

1. WhatsApp Business API integration
2. Webhook handling for incoming messages
3. Message templating (required for initial contact)
4. Rate limiting and conversation tracking
5. Business verification documentation

See [CONTRIBUTING.md](/docs/contributing) for guidelines.

---

## What Would Be Needed

### Technical Requirements

**WhatsApp Business API:**
- Meta Business account
- Business verification
- Phone number for WhatsApp
- Cloud API or On-premises API setup

**Implementation:**
- Webhook endpoint for message callbacks
- Message template management
- Conversation session tracking
- Media message support (optional)

### Pricing Considerations

WhatsApp charges per conversation:
- User-initiated: ~$0.005-0.08 USD depending on region
- Business-initiated (with template): ~$0.05-0.15 USD
- 24-hour session window

See [WhatsApp Business Pricing](https://business.whatsapp.com/products/business-platform) for current rates.

### Use Cases

WhatsApp would be suitable for:
- Customer support bots
- Appointment reminders
- Order notifications
- Personal assistants

---

## Alternatives

If you need mobile messaging:

- **Discord:** Free, works on mobile, rich features
- **Slack:** (Coming Q2 2026) Mobile apps available
- **Web Interface:** (Coming Q2 2026) Mobile browser access

---

## Vote for This Feature

Add a 👍 reaction to [this issue](https://github.com/ric03uec/clawrium/issues) to help us prioritize.

---

[Back to Channels](index.md)
