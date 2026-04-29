# ANP · Agent Negotiation Protocol

**The economic layer missing from the AI agent stack.**

[![License: MIT](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![CPU only](https://img.shields.io/badge/GPU-not%20required-green.svg)]()
[![Status: Alpha](https://img.shields.io/badge/status-alpha-orange.svg)]()

```
[BUYER ] → WIRE  01 13 37 00 01 00 00 00 0E ...  [BID]     api_access  max=$0.10
[SELLER] ← WIRE  02 13 37 00 02 00 00 00 0C ...  [OFFER]   $0.07
[BUYER ] → WIRE  04 13 37 00 01 00 00 00 02 ...  [ACCEPT]  $0.07  ✓

✓ Deal closed in 3 messages · 55 bytes · 0.3ms · $0.0000 in LLM tokens
```

---

## The problem

MCP moves context. A2A moves tasks. ACP moves messages.

**Nobody moves value.**

When two AI agents need to agree on a price, they either:
- Have a human decide (slow, doesn't scale)
- Use an LLM to negotiate in natural language (expensive, ambiguous, hallucinates prices)
- Hardcode the price (inflexible, leaves money on the table)

ANP is the fourth option: a **binary wire protocol** where agents negotiate price, prove identity, and enforce spending limits — without a single LLM token.

---

## What ANP does

```
Without ANP                          With ANP
────────────────────────────         ────────────────────────────
GPT-4: "I would like to              01 1337 0001 0E [BID $0.10]
purchase the API access              02 1337 0002 0C [OFFER $0.07]
for perhaps around eight             04 1337 0001 02 [ACCEPT]
cents, if that works..."
                                     3 messages. 55 bytes. Done.
~400 tokens. ~$0.002.
```

1,000 negotiations/day:
- **With LLM:** ~$2.00/day, ~400ms each, hallucination risk
- **With ANP:** ~$0.00/day, ~0.3ms each, mathematically exact

---

## The stack

```
┌─────────────────────────────────────────┐
│  Your LLM (GPT-4, Claude, Llama, etc.) │  ← speaks human language
│  ANP Wrapper (function calling)         │  ← translates intent → wire
├─────────────────────────────────────────┤
│  M1 · Negotiation Engine               │  ← BID/OFFER/COUNTER/ACCEPT
│  M2 · Price Oracle                     │  ← blocks hallucinated prices
│  M3 · ANP-Pass Token                   │  ← spending limits + scope
│  M4 · Ed25519 Identity                 │  ← agent authentication
├─────────────────────────────────────────┤
│  M0 · ANP-Wire (binary protocol)       │  ← 9-byte header, 10:1 vs JSON
└─────────────────────────────────────────┘
```

ANP sits **on top of** MCP, A2A, and ACP — it doesn't compete with them. It's the economic layer they're all missing.

---

## Quickstart

```bash
pip install pynacl msgpack rich fastapi uvicorn
git clone https://github.com/yourname/anp
cd anp
```

### See two agents negotiate in your terminal

```bash
python demos/terminal_demo.py
```

### Use ANP from Python directly

```python
from wrappers import anp_negotiate

result = anp_negotiate(
    item="api_access_basic",
    max_price=0.08,
    seller_start=0.09,
    seller_min=0.04,
)

print(result.final_price)   # 0.07
print(result.bytes_wire)    # 55
print(result.elapsed_ms)    # 0.3
```

### Use ANP with OpenAI

```python
import openai
from wrappers import ANPOpenAIWrapper

client = openai.OpenAI(api_key="...")
wrapper = ANPOpenAIWrapper(client, model="gpt-4o-mini")

response = wrapper.chat(
    "I need API access for less than $0.08 per call"
)
# → "Done. Negotiated api_access_basic at $0.07. ANP closed the deal
#    in 3 rounds using 55 bytes. Zero negotiation tokens consumed."
```

### Use ANP with Claude

```python
import anthropic
from wrappers import ANPAnthropicWrapper

client = anthropic.Anthropic(api_key="...")
wrapper = ANPAnthropicWrapper(client)

response = wrapper.chat(
    "Find shared hosting under $9/month, negotiate the best price"
)
```

### Start the REST API

```bash
uvicorn anp.api.server:app --port 8000
# → http://localhost:8000/docs
```

---

## The wire protocol

Every ANP message is a **9-byte header + compact binary payload**.

```
Offset  Bytes  Field
──────────────────────────────────────
0       1      opcode  (BID=0x01, OFFER=0x02, COUNTER=0x03, ACCEPT=0x04 ...)
1       2      tx_id   (uint16, shared across session)
3       2      agent_id
5       4      payload_len
9       N      payload (struct-packed, no strings)
```

| Message | ANP-Wire | JSON equivalent | Ratio |
|---------|----------|-----------------|-------|
| BID     | 23 bytes | ~180 bytes      | 8:1   |
| OFFER   | 21 bytes | ~140 bytes      | 7:1   |
| ACCEPT  | 11 bytes | ~80 bytes       | 7:1   |
| Full negotiation | **55 bytes** | **~600 bytes** | **10:1** |

Prices are `int32` fixed-point (cents), not floats. No rounding errors. No ambiguity.

---

## Security model

ANP is inspired by Bitcoin's security design: **you hold the keys, the agent obeys**.

### ANP-Pass Token (M3)
Every agent carries a signed token that defines exactly what it can do:

```python
token = {
    "agent_id":     "agent-uuid",
    "budget_usd":   10.00,        # total spending limit
    "budget_per_tx": 2.00,        # per-transaction limit
    "scope":        ["api:*"],    # what it can negotiate
    "expires_at":   unix_ts,      # TTL
    "allowed_sellers": [...],     # whitelist
    "blocked_sellers": [...],     # blacklist
}
# Signed with HMAC-SHA256. 160 bytes. Fits in an HTTP header.
```

Without a valid token: zero negotiations. Without the issuer's key: impossible to forge.

### Ed25519 Identity (M4)
Every agent has a cryptographic identity derived from a private key — like a Bitcoin address:

```
private key (32 bytes, secret)
    ↓
public key (32 bytes, share freely)
    ↓
agent_id = SHA256(pubkey)[:32]  ← deterministic, no central registry
```

The seller verifies: "this agent signed this AUTH with the key that matches this agent_id." Impersonation requires breaking Ed25519 — that's 2^128 operations.

### Price Oracle (M2)
LLMs hallucinate numbers. The oracle catches it before money moves:

```python
# LLM "thinks" the price is $5.00 for a $0.05 API call
result = oracle.check_buy("api_access_basic", offered_price=5.00)
# → BLOCKED_CEILING: $5.00 > ceiling $0.20. Saved: $4.80
```

Three layers: hard ceiling (absolute block), soft tolerance (±20%, human confirmation), and a real-time savings tracker that shows exactly how much money the oracle saved.

---

## Modules

| Module | File | What it does |
|--------|------|--------------|
| M0 · Wire | `anp/wire/` | Binary protocol, opcodes, frame codec |
| M1 · Negotiation | `anp/negotiation/` | Engine, buyer, seller, strategies |
| M2 · Oracle | `anp/oracle/` | Price validation, x402/MPP integration |
| M3 · Passport | `anp/passport/` | HMAC token, permissions, anti-replay |
| M4 · Identity | `anp/identity/` | Ed25519 keypair, registry, credentials |
| M5 · API | `anp/api/` | FastAPI server, 11 endpoints |
| M6 · Wrappers | `wrappers/` | OpenAI, Anthropic, LangChain, pure Python |

---

## Run the demos

```bash
python demos/terminal_demo.py    # two agents negotiate live
python demos/oracle_demo.py      # see the oracle block hallucinated prices
python demos/passport_demo.py    # token lifecycle and permission enforcement
python demos/identity_demo.py    # Ed25519 auth + 5 attack types blocked
python demos/wrapper_demo.py     # LLM + ANP integration simulation
```

---

## x402 / MPP integration

When a transaction exceeds the configured threshold (default $1.00), ANP signals that it should route through an x402 or Lightning MPP payment channel before executing:

```python
oracle = Oracle.from_json(
    "feeds/prices.json",
    x402_endpoint="https://payments.example.com/x402",
    x402_threshold_usd=1.0,
)

result = oracle.check_buy("hosting_shared_monthly", 8.99)
# result.x402_required == True
# result.x402_endpoint == "https://payments.example.com/x402"
```

The negotiation closes in ANP-Wire. The payment settles in x402. Two separate concerns, cleanly separated.

---

## Why not JSON-RPC?

JSON-RPC handles transport. ANP handles **semantics**.

JSON-RPC doesn't know what `BID` means, that a `COUNTER` price can't exceed the previous `OFFER`, that `ACCEPT` is irrevocable within a session, or that prices are fixed-point integers with no ambiguity. ANP encodes those invariants in the protocol itself.

It's the difference between having wires and having TCP/IP.

---

## Roadmap

- [x] M0 · ANP-Wire binary protocol
- [x] M1 · Negotiation engine (3 buyer strategies, 2 seller strategies)
- [x] M2 · Price oracle + x402 integration
- [x] M3 · ANP-Pass capability token
- [x] M4 · Ed25519 agent identity + TOFU registry
- [x] M5 · FastAPI REST server
- [x] M6 · OpenAI, Anthropic, LangChain wrappers
- [ ] WebSocket transport for real-time multi-agent sessions
- [ ] Persistent price feed (connect to live market APIs)
- [ ] Multi-seller auction (N sellers competing for one buyer)
- [ ] ANP-Pass revocation registry
- [ ] SPEC.md RFC formalization
- [ ] PR to LangChain, CrewAI, AutoGen for native integration

---

## Contributing

ANP is designed to be **the standard**, not a library. That means:

1. The wire protocol must stay simple enough for any AI (GPT-3 to GPT-4) to generate correct calls
2. Every new opcode needs a strong reason — the table has 255 slots and we've used 11
3. The SPEC.md (coming soon) is the source of truth — implementations follow the spec, not the other way around

If you implement ANP in another language (Go, Rust, TypeScript), open a PR and we'll link it here.

---

## License

MIT. Use it, build on it, make it the standard.

---
Current limitations

Single price feed (JSON local) — production deployments need live market data sources
Bilateral sessions only — multi-seller auction mode is on the roadmap (v0.2)
Negotiation strategies are rule-based, not game-theoretic — sophisticated counterparties may exploit predictable patterns
Python reference implementation only — SPEC.md with test vectors coming before v1.0
Python reference implementation only — SPEC.md with test vectors coming before v1.0
*ANP · The economic layer for agent-to-agent negotiation.*  
*MCP moves context. A2A moves tasks. ANP moves value.*
