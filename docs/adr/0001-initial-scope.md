# ADR 0001: Initial scope

## Status

Accepted

## Context

The project is intended to demonstrate AI engineering, backend engineering,
stateful workflows, safety, reliability, observability, and evaluation. A
large initial architecture would make it difficult to know which behavior is
correct and why.

## Decision

Build in layers. V0 defines a deterministic, auditable incident-response
workflow with explicit state, typed decisions, tool contracts, policy checks,
approval boundaries, persistence, and tests. The first repository milestone
establishes the development and database foundation before agent behavior is
implemented.

The LLM is not trusted with state transitions, permissions, or direct side
effects. Dangerous actions require explicit approval.

## Alternatives considered

- **Chatbot-first:** rejected because it does not provide durable state,
  controlled execution, or reliable auditability.
- **Framework-first:** rejected because adding an orchestration framework
  before understanding the runtime would hide important semantics.
- **Full production stack immediately:** rejected because distributed systems,
  multiple providers, and infrastructure would add complexity before there is
  a measurable requirement.

## Consequences

The early system will be smaller and less autonomous, but its behavior will be
understandable and testable. More infrastructure may be added later when a
concrete requirement, measurement, or failure mode justifies it.
