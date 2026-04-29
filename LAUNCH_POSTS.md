# HACKERNEWS POST
# Title (max 80 chars):
ANP – A binary protocol for agent-to-agent price negotiation (no LLM tokens)

# URL: tu link de GitHub

# Text (se pega en el campo "text" si es un Ask HN):
─────────────────────────────────────────────────────

Ask HN: I built a binary protocol for AI agents to negotiate price without LLMs

MCP moves context. A2A moves tasks. Nobody moves value.

When two AI agents need to agree on a price today, they either use an LLM 
(slow, expensive, hallucinates numbers) or hardcode it (inflexible).

I built ANP (Agent Negotiation Protocol): a 9-byte binary frame format where 
agents negotiate BID/OFFER/COUNTER/ACCEPT in pure logic, without consuming 
a single token during negotiation.

A full negotiation — buyer, seller, 3 rounds, deal closed — is 55 bytes 
and takes 0.3ms. The JSON equivalent is ~600 bytes. The LLM equivalent 
would be ~400 tokens (~$0.002 per negotiation).

At 1,000 negotiations/day that's the difference between $0 and $730/year 
in pure negotiation overhead.

The stack:
- ANP-Wire: binary protocol (9B header, fixed-point prices, no floats)
- Negotiation engine: 3 buyer strategies, 2 seller strategies
- Price oracle: blocks hallucinated prices before money moves (caught $1,132 
  in fake prices in a single test session)
- ANP-Pass: HMAC-SHA256 capability token (budget limit, scope, TTL, seller whitelist)
- Ed25519 identity: Bitcoin-style agent auth, no central registry
- FastAPI server: 11 endpoints, Swagger at /docs
- Wrappers: OpenAI function calling, Claude tool use, LangChain, pure Python

It's not competing with MCP or A2A — it sits on top as the economic layer 
they're missing. Compatible with x402/MPP for the actual payment settlement.

100% CPU. No GPU. Runs on a $300 laptop. 40 files, ~2,500 lines of Python.

GitHub: [link]

The part I'm most unsure about: is the right move to push for this to be 
adopted as a standard (get PRs into LangChain/CrewAI/AutoGen), or to 
build a SaaS layer on top first to show real traction?

─────────────────────────────────────────────────────

# TWITTER/X THREAD (pegar como hilo):
─────────────────────────────────────────────────────

Tweet 1:
I built a protocol so AI agents can negotiate price with each other.
No LLM tokens. No natural language. Pure binary.

A full negotiation is 55 bytes and takes 0.3ms.

[GIF del terminal demo]

Thread 🧵

Tweet 2:
The problem:

When two AI agents need to agree on a price today, they either:
• Use an LLM to negotiate in English → slow, expensive, hallucinates numbers
• Hardcode it → inflexible, no optimization
• Have a human decide → doesn't scale

There's no protocol for this. So I built one.

Tweet 3:
ANP-Wire: a binary frame with a 9-byte header.

BID  = 23 bytes
OFFER = 21 bytes  
ACCEPT = 11 bytes
Full negotiation = 55 bytes

vs JSON equivalent: ~600 bytes
vs LLM negotiation: ~400 tokens

Ratio: 10:1

Tweet 4:
Prices are int32 fixed-point (cents), not floats.

$0.07 → 7
$10.50 → 1050

No rounding errors. No "approximately eight cents". No ambiguity.
PRICE < 10.50 is a mathematical rule, not a subjective opinion.

Tweet 5:
The oracle catches LLM hallucinations before money moves.

In one test session: 6 hallucinated prices detected, $1,132 USD in 
fake overpricing blocked.

LLMs genuinely confuse $0.05 with $5.00. The oracle doesn't.

Tweet 6:
Security is inspired by Bitcoin:

private key → public key → agent_id (like a BTC address)

The agent signs every AUTH frame. The seller verifies without 
knowing the private key. Impersonation = breaking Ed25519 = 2^128 ops.

Tweet 7:
The LLM integration is clean:

User: "I need API access for less than $0.08 per call"

LLM: [calls anp_negotiate with the right params]
ANP: [negotiates in binary, 0 tokens consumed]
LLM: "Done. Got it at $0.07 in 3 rounds."

The LLM only uses tokens for intent + response. Not for negotiation.

Tweet 8:
It's not competing with MCP, A2A, or ACP.

MCP moves context.
A2A moves tasks.
ACP moves messages.
ANP moves value.

It sits on top as the economic layer they're all missing.

Tweet 9:
100% CPU. No GPU. Runs on a $300 laptop.
40 files. ~2,500 lines of Python.
MIT license.

GitHub: [link]

The question I'm thinking about: standard first or SaaS first?

Tweet 10 (responder al 1):
Stack:
• ANP-Wire: binary protocol
• Negotiation engine: 3 strategies  
• Price oracle: anti-hallucination
• ANP-Pass: capability token (budget, scope, TTL)
• Ed25519 identity: no central registry
• FastAPI: 11 endpoints
• Wrappers: OpenAI, Claude, LangChain

pip install pynacl msgpack rich fastapi
github: [link]

─────────────────────────────────────────────────────

# LINKEDIN POST (más formal, para el ángulo B2B):
─────────────────────────────────────────────────────

The AI agent stack has a missing layer: economics.

MCP (Anthropic) connects agents to tools.
A2A (Google) connects agents to agents.
ACP (IBM) connects agents to editors.

None of them handle price negotiation between agents.

I spent the last few weeks building ANP — Agent Negotiation Protocol — 
a binary wire format for Bot-to-Bot price negotiation.

The numbers:
• A full negotiation: 55 bytes, 0.3ms, $0 in LLM tokens
• The LLM alternative: ~400 tokens, ~400ms, ~$0.002 per negotiation
• At 1,000 negotiations/day: $730/year saved in negotiation overhead alone

The security model is inspired by Bitcoin:
• Ed25519 keypairs — agents can't impersonate each other
• HMAC-signed capability tokens — agents can't exceed their spending limit
• Price oracle — blocks hallucinated prices before money moves

It's not a startup pitch. It's an open protocol.
The value comes from adoption, not from a paywall.

If you're building AI agents that need to interact with commercial services,
I'd love to hear whether this solves a real problem for you.

GitHub: [link]
#AIAgents #Protocol #OpenSource #MCP #LLM

─────────────────────────────────────────────────────

# PARA EL GIF DEL TERMINAL:
# Graba la pantalla mientras corres: python demos/terminal_demo.py
# Convierte a GIF con: ffmpeg o ShareX (Windows) o Kap (Mac)
# Tamaño ideal: 800x400px, max 5MB para Twitter
# La parte más impactante: el panel final con "55 bytes vs 605 bytes"
